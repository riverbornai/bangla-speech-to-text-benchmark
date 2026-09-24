"""
Gemini Live API, input audio transcription -- streaming benchmark adapter.

Verified against Google's Live API guide and reference
(https://ai.google.dev/gemini-api/docs/live-guide,
https://ai.google.dev/api/live -- BidiGenerateContentServerContent fields)
and the installed `google-genai` SDK's own type definitions
(google.genai.types.Transcription, LiveServerContent), and run against the
live API for the published benchmark results.

The Live API is a bidirectional conversational API (audio/text in, model
response out), not a dedicated ASR endpoint like the other adapters here --
but setting `input_audio_transcription: {}` in the session config turns on
a genuine ASR side-channel with real interim/final semantics, independent
of whatever the model itself generates in response:
  - `interimInputTranscription` ("subject to frequent updates" per the
    docs): the partial hypothesis while the user is still speaking.
  - `inputTranscription`: the more stable transcription; whatever value it
    holds when `turnComplete` fires is this adapter's final transcript.
`response_modalities` is set to `["AUDIO"]`, matching the docs' example --
"native audio" Live models (like the default below) only support AUDIO
responses and reject a TEXT-only request with a 1007 API error. This is
harmless for the benchmark: `interim_input_transcription`/
`input_transcription` arrive on `server_content` independently of the
response modality, and this adapter never reads the generated audio bytes.

Audio is sent as `audio/pcm;rate=16000` mono, which matches BanSpeech's
native format exactly -- no resampling needed (unlike the OpenAI adapter).

Turn boundaries are automatic-VAD by default (not overridden here); after
the last chunk this adapter also sends `audio_stream_end=True` as a
force-finalize fallback for clips with no trailing silence for VAD to key
off of.

Live/preview model ids are date-versioned and get replaced frequently --
if `cfg["model"]`'s default 404s, check
https://ai.google.dev/gemini-api/docs/models for the current Live-capable
model id.
"""
import asyncio
import os
import time
import wave

from google import genai
from google.genai import types

DEFAULT_CHUNK_MS = 100
DEFAULT_MODEL = "gemini-2.5-flash-native-audio-preview-12-2025"


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


async def _stream(wav_path: str, cfg: dict) -> dict:
    chunk_ms = cfg.get("chunk_ms", DEFAULT_CHUNK_MS)
    chunks, sample_rate, sampwidth, audio_duration_s = _read_pcm_chunks(wav_path, chunk_ms)
    if sampwidth != 2:
        raise ValueError(f"{wav_path}: expected 16-bit PCM wav, got {sampwidth * 8}-bit")

    client = genai.Client(api_key=os.environ[cfg["api_key_env"]])
    model = cfg.get("model", DEFAULT_MODEL)

    first_partial_latency_s = None
    first_final_latency_s = None
    last_result_latency_s = None
    num_partial = 0
    num_final = 0
    final_segments = []
    partial_transcripts = []

    t0 = time.perf_counter()

    config = {
        "response_modalities": ["AUDIO"],
        "input_audio_transcription": {},
    }

    async with client.aio.live.connect(model=model, config=config) as session:

        async def send_audio():
            chunk_s = chunk_ms / 1000
            mime_type = f"audio/pcm;rate={sample_rate}"
            for chunk in chunks:
                t_chunk_start = time.perf_counter()
                await session.send_realtime_input(audio=types.Blob(data=chunk, mime_type=mime_type))
                # Pace sends to real time -- without this every chunk lands
                # instantly and "first partial/final" latency stops meaning
                # anything relative to a live mic feed.
                sleep_for = chunk_s - (time.perf_counter() - t_chunk_start)
                if sleep_for > 0:
                    await asyncio.sleep(sleep_for)
            # Force-finalize in case there's no trailing silence for VAD to
            # detect the end of the utterance on.
            await session.send_realtime_input(audio_stream_end=True)

        async def receive_events():
            nonlocal first_partial_latency_s, first_final_latency_s, last_result_latency_s
            nonlocal num_partial, num_final
            async for msg in session.receive():
                t_now = time.perf_counter() - t0
                content = getattr(msg, "server_content", None)
                if content is None:
                    continue

                interim = getattr(content, "interim_input_transcription", None)
                if interim is not None and interim.text:
                    num_partial += 1
                    partial_transcripts.append({"t": round(t_now, 3), "transcript": interim.text})
                    if first_partial_latency_s is None:
                        first_partial_latency_s = t_now
                    last_result_latency_s = t_now

                final = getattr(content, "input_transcription", None)
                if final is not None and final.text:
                    num_final += 1
                    final_segments.append(final.text)
                    if first_final_latency_s is None:
                        first_final_latency_s = t_now
                    last_result_latency_s = t_now

                if getattr(content, "turn_complete", False):
                    return

        send_task = asyncio.create_task(send_audio())
        recv_task = asyncio.create_task(receive_events())
        try:
            await asyncio.wait_for(asyncio.gather(send_task, recv_task), timeout=audio_duration_s + 30)
        except asyncio.TimeoutError:
            pass

    total_latency_s = time.perf_counter() - t0
    # input_transcription updates the SAME turn's transcript rather than
    # appending independent segments -- the last value seen is the fullest.
    transcript = (final_segments[-1] if final_segments else "").strip()

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
