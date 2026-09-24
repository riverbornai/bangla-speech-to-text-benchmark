"""
ElevenLabs Scribe -- streaming benchmark adapter.

Protocol verified against ElevenLabs' published AsyncAPI spec:
https://elevenlabs.io/docs/api-reference/speech-to-text/v-1-speech-to-text-realtime

  - wss://api.elevenlabs.io/v1/speech-to-text/realtime
    ?model_id=<model>&audio_format=pcm_16000&language_code=<code>
    &commit_strategy=<manual|vad>&...
  - auth via the `xi-api-key` header (same header as the batch REST
    endpoint in elevenlabs.py)
  - client sends raw 16-bit PCM mono audio as JSON messages:
    {"message_type": "input_audio_chunk", "audio_base_64": "<base64>",
     "commit": bool, "sample_rate": 16000}, paced in real time; `commit`
    is set true on the final chunk to force-finalize regardless of
    commit_strategy (a safety net for short clips with no trailing silence
    for VAD to key off of)
  - server sends {"message_type": "session_started", ...},
    {"message_type": "partial_transcript", "text": "..."} throughout the
    utterance, {"message_type": "committed_transcript", "text": "..."} at
    each finalized segment, {"message_type": "warning", ...} (non-fatal),
    and various fatal error types (auth_error, quota_exceeded,
    rate_limited, input_error, invalid_request, transcriber_error, etc.)
    all shaped {"message_type": "<type>", "error": "..."}

Send and receive run on separate threads (a sync `websockets` connection
supports concurrent send/recv) so partial/final timestamps reflect when
the server actually emitted them, not when we got around to reading the
socket after finishing the send loop.
"""
import base64
import json
import os
import threading
import time
import wave

import websockets
import websockets.sync.client as ws_client

DEFAULT_CHUNK_MS = 100
WS_ENDPOINT = "wss://api.elevenlabs.io/v1/speech-to-text/realtime"
FATAL_MESSAGE_TYPES = {
    "error", "auth_error", "quota_exceeded", "commit_throttled",
    "unaccepted_terms", "rate_limited", "queue_overflow",
    "resource_exhausted", "session_time_limit_exceeded", "input_error",
    "invalid_request", "chunk_size_exceeded",
    "insufficient_audio_activity", "transcriber_error",
}
SAMPLE_RATE_FORMATS = {8000: "pcm_8000", 16000: "pcm_16000", 22050: "pcm_22050",
                       24000: "pcm_24000", 44100: "pcm_44100", 48000: "pcm_48000"}


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


def stream_transcribe(wav_path: str, cfg: dict) -> dict:
    api_key = os.environ[cfg["api_key_env"]]
    chunk_ms = cfg.get("chunk_ms", DEFAULT_CHUNK_MS)

    chunks, sample_rate, sampwidth, audio_duration_s = _read_pcm_chunks(wav_path, chunk_ms)
    if sampwidth != 2:
        raise ValueError(f"{wav_path}: expected 16-bit PCM wav, got {sampwidth * 8}-bit")
    if sample_rate not in SAMPLE_RATE_FORMATS:
        raise ValueError(f"{wav_path}: unsupported sample rate {sample_rate} for ElevenLabs realtime STT")

    url = (
        f"{WS_ENDPOINT}?model_id={cfg.get('model_id', 'scribe_v1')}"
        f"&audio_format={SAMPLE_RATE_FORMATS[sample_rate]}"
        f"&commit_strategy={cfg.get('commit_strategy', 'vad')}"
    )
    if cfg.get("language_code"):
        url += f"&language_code={cfg['language_code']}"

    first_partial_latency_s = None
    first_final_latency_s = None
    last_result_latency_s = None
    num_partial = 0
    num_final = 0
    final_segments = []
    partial_transcripts = []
    state = {"fatal_error": None, "send_done": False}

    t0 = time.perf_counter()

    with ws_client.connect(url, additional_headers={"xi-api-key": api_key}) as ws:

        def sender():
            chunk_s = chunk_ms / 1000
            try:
                for i, chunk in enumerate(chunks):
                    t_chunk_start = time.perf_counter()
                    ws.send(json.dumps({
                        "message_type": "input_audio_chunk",
                        "audio_base_64": base64.b64encode(chunk).decode("ascii"),
                        "commit": i == len(chunks) - 1,
                        "sample_rate": sample_rate,
                    }))
                    # Pace sends to real time -- without this every chunk
                    # lands instantly and "first partial/final" latency
                    # stops meaning anything relative to a live mic feed.
                    sleep_for = chunk_s - (time.perf_counter() - t_chunk_start)
                    if sleep_for > 0:
                        time.sleep(sleep_for)
            except Exception:
                pass  # surfaced via the receive loop's own error/close handling
            finally:
                state["send_done"] = True

        sender_thread = threading.Thread(target=sender, daemon=True)
        sender_thread.start()

        deadline = t0 + audio_duration_s + 30
        while time.perf_counter() < deadline:
            try:
                raw = ws.recv(timeout=1)
            except TimeoutError:
                if state["send_done"] and num_final > 0:
                    break
                continue
            except websockets.exceptions.ConnectionClosed:
                break
            if isinstance(raw, (bytes, bytearray)):
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            mtype = msg.get("message_type")
            if mtype == "partial_transcript":
                t_now = time.perf_counter() - t0
                num_partial += 1
                partial_transcripts.append({"t": round(t_now, 3), "transcript": msg.get("text", "")})
                if first_partial_latency_s is None:
                    first_partial_latency_s = t_now
                last_result_latency_s = t_now
            elif mtype in ("committed_transcript", "committed_transcript_with_timestamps"):
                t_now = time.perf_counter() - t0
                num_final += 1
                final_segments.append(msg.get("text", ""))
                if first_final_latency_s is None:
                    first_final_latency_s = t_now
                last_result_latency_s = t_now
                if state["send_done"]:
                    break
            elif mtype in FATAL_MESSAGE_TYPES:
                state["fatal_error"] = f"{mtype}: {msg.get('error')}"
                break
            # session_started / committed_transcript_entities / warning: ignore

        sender_thread.join(timeout=5)

    if state["fatal_error"]:
        raise RuntimeError(f"ElevenLabs realtime error: {state['fatal_error']}")

    total_latency_s = time.perf_counter() - t0
    transcript = " ".join(s for s in final_segments if s).strip()

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
