"""
OpenAI gpt-4o-transcribe (Realtime API, transcription-only session) --
streaming benchmark adapter.

Verified against the installed `openai` SDK's own type definitions
(openai.types.realtime.realtime_transcription_session_create_request and
friends) and iterated against live-run errors. The session type is fixed
at connect time and can't be changed afterwards:
  - `connect(model=...)` alone opens a **realtime** (conversational)
    session. Sending it a `session.update` of type "transcription"
    afterwards is rejected: "Passing a transcription session update to a
    realtime session is not allowed."
  - `connect(extra_query={"intent": "transcription"})` opens a
    **transcription** session directly -- no `model=` needed or accepted
    here, since a transcription session has no conversational model, only
    the ASR model set inside the transcription-session config below.
This adapter uses the `intent=transcription` form for exactly that reason.

Uses `client.realtime.connect()` in transcription-session mode: input audio
is transcribed asynchronously by a dedicated ASR model without spinning up
a full conversational response, turn-delimited by server VAD. Partial
results arrive as `conversation.item.input_audio_transcription.delta`
events (incremental text to append to a running transcript); the turn
finalizes with a `.completed` event carrying the full transcript.

OpenAI's Realtime API only accepts 24kHz PCM16 mono input
(openai.types.realtime.realtime_audio_formats.AudioPCM.rate is literally
`24000`, no other rate), so BanSpeech's native 16kHz audio is upsampled
with simple linear interpolation before sending -- adequate for a
benchmark, not audiophile-grade resampling.
"""
import asyncio
import base64
import os
import time
import wave

import numpy as np
from openai import AsyncOpenAI

DEFAULT_CHUNK_MS = 100
TARGET_SAMPLE_RATE = 24000  # the only rate the Realtime API's PCM format supports


def _read_pcm_chunks(wav_path: str, chunk_ms: int):
    with wave.open(wav_path, "rb") as w:
        sample_rate = w.getframerate()
        sampwidth = w.getsampwidth()
        n_frames = w.getnframes()
        duration_s = n_frames / sample_rate
        frames_per_chunk = max(1, int(sample_rate * chunk_ms / 1000))
        chunks = []
        while True:
            data = w.readframes(frames_per_chunk)
            if not data:
                break
            chunks.append(data)
    return chunks, sample_rate, sampwidth, duration_s


def _resample_pcm16(pcm_bytes: bytes, orig_sr: int, target_sr: int) -> bytes:
    if orig_sr == target_sr or not pcm_bytes:
        return pcm_bytes
    samples = np.frombuffer(pcm_bytes, dtype="<i2").astype(np.float32)
    n_out = max(1, round(len(samples) * target_sr / orig_sr))
    x_old = np.linspace(0.0, 1.0, num=len(samples), endpoint=False)
    x_new = np.linspace(0.0, 1.0, num=n_out, endpoint=False)
    return np.interp(x_new, x_old, samples).astype("<i2").tobytes()


async def _stream(wav_path: str, cfg: dict) -> dict:
    chunk_ms = cfg.get("chunk_ms", DEFAULT_CHUNK_MS)
    chunks, sample_rate, sampwidth, audio_duration_s = _read_pcm_chunks(wav_path, chunk_ms)
    if sampwidth != 2:
        raise ValueError(f"{wav_path}: expected 16-bit PCM wav, got {sampwidth * 8}-bit")

    client = AsyncOpenAI(api_key=os.environ[cfg["api_key_env"]])

    first_partial_latency_s = None
    first_final_latency_s = None
    last_result_latency_s = None
    num_partial = 0
    num_final = 0
    final_segments = []
    partial_transcripts = []
    state = {"partial_text": "", "error": None}

    t0 = time.perf_counter()

    # intent=transcription opens a transcription session directly (see the
    # module docstring) -- no model= here; the ASR model is configured
    # below, inside the transcription-session's own config.
    transcription_model = cfg.get("model", "gpt-4o-transcribe")
    async with client.realtime.connect(extra_query={"intent": "transcription"}) as connection:
        await connection.session.update(session={
            "type": "transcription",
            "audio": {
                "input": {
                    "format": {"type": "audio/pcm", "rate": TARGET_SAMPLE_RATE},
                    "transcription": {
                        "model": transcription_model,
                        "language": cfg.get("language", "bn"),
                    },
                    "turn_detection": {
                        "type": "server_vad",
                        "silence_duration_ms": cfg.get("vad_silence_ms", 500),
                    },
                },
            },
        })

        async def send_audio():
            chunk_s = chunk_ms / 1000
            for chunk in chunks:
                t_chunk_start = time.perf_counter()
                resampled = _resample_pcm16(chunk, sample_rate, TARGET_SAMPLE_RATE)
                await connection.input_audio_buffer.append(
                    audio=base64.b64encode(resampled).decode("ascii")
                )
                # Pace sends to real time -- without this every chunk lands
                # instantly and "first partial/final" latency stops meaning
                # anything relative to a live mic feed.
                sleep_for = chunk_s - (time.perf_counter() - t_chunk_start)
                if sleep_for > 0:
                    await asyncio.sleep(sleep_for)
            try:
                # Force-finalize in case there's no trailing silence for
                # server VAD to detect the end of the utterance on. If VAD
                # already auto-committed, the buffer is empty and this
                # raises -- harmless, ignore it.
                await connection.input_audio_buffer.commit()
            except Exception:
                pass

        async def receive_events():
            nonlocal first_partial_latency_s, first_final_latency_s, last_result_latency_s
            nonlocal num_partial, num_final
            async for event in connection:
                t_now = time.perf_counter() - t0
                etype = getattr(event, "type", None)
                if etype == "conversation.item.input_audio_transcription.delta":
                    state["partial_text"] += getattr(event, "delta", None) or ""
                    num_partial += 1
                    partial_transcripts.append({"t": round(t_now, 3), "transcript": state["partial_text"]})
                    if first_partial_latency_s is None:
                        first_partial_latency_s = t_now
                    last_result_latency_s = t_now
                elif etype == "conversation.item.input_audio_transcription.completed":
                    num_final += 1
                    final_segments.append(getattr(event, "transcript", "") or "")
                    if first_final_latency_s is None:
                        first_final_latency_s = t_now
                    last_result_latency_s = t_now
                    return
                elif etype == "conversation.item.input_audio_transcription.failed":
                    err = getattr(event, "error", None)
                    state["error"] = getattr(err, "message", None) or str(err) or "transcription failed"
                    return
                elif etype == "error":
                    err = getattr(event, "error", None)
                    state["error"] = getattr(err, "message", None) or str(err) or "realtime error"
                    return

        send_task = asyncio.create_task(send_audio())
        recv_task = asyncio.create_task(receive_events())
        try:
            await asyncio.wait_for(asyncio.gather(send_task, recv_task), timeout=audio_duration_s + 30)
        except asyncio.TimeoutError:
            pass

    if state["error"]:
        raise RuntimeError(f"OpenAI realtime transcription error: {state['error']}")

    total_latency_s = time.perf_counter() - t0
    transcript = " ".join(s for s in final_segments if s).strip() or state["partial_text"].strip()

    return {
        "transcript": transcript,
        "audio_duration_s": round(audio_duration_s, 3),
        "total_latency_s": round(total_latency_s, 3),
        "first_partial_latency_s": round(first_partial_latency_s, 3) if first_partial_latency_s is not None else None,
        "first_final_latency_s": round(first_final_latency_s, 3) if first_final_latency_s is not None else None,
        "last_result_latency_s": round(last_result_latency_s, 3) if last_result_latency_s is not None else None,
        "finalization_latency_s": round(total_latency_s - audio_duration_s, 3),
        "rtf": round(total_latency_s / audio_duration_s, 4) if audio_duration_s else None,
        "num_partial_results": num_partial,
        "num_final_results": num_final,
        "partial_transcripts": partial_transcripts,
    }


def stream_transcribe(wav_path: str, cfg: dict) -> dict:
    return asyncio.run(_stream(wav_path, cfg))
