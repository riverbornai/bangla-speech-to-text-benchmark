"""
Sarvam AI Realtime Streaming speech-to-text -- streaming benchmark adapter.

Uses the `speech-to-text-realtime` endpoint (`saaras:v3-realtime` /
`saaras:v4-realtime`), NOT the older `speech-to-text` streaming endpoint
that the batch adapter's model family (`saarika:v2.5`) belongs to -- that
legacy endpoint only ever returns one final transcript per utterance and
has no interim/partial events, so it can't produce the latency metrics this
benchmark measures. Protocol verified against Sarvam's docs:
https://docs.sarvam.ai/api/api-guides-tutorials/speech-to-text/realtime-streaming

  - wss://api.sarvam.ai/speech-to-text-realtime/ws
    ?language_code=<bcp47>&model=<model>&stream_type=<fast|balanced|simulated>
    &encoding=linear16&sample_rate=<8000|16000>
  - auth via the `api-subscription-key` header
  - client sends raw 16-bit PCM mono ("linear16") audio, base64-encoded,
    wrapped as {"event": "audio_input", "audio": "<base64>"}, paced in real
    time to simulate a live mic feed, then {"event": "end"} to close out
  - server sends {"event": "transcript.partial", "text": "..."} throughout
    the utterance and {"event": "transcript.final", "text": "..."} at each
    turn boundary (VAD-driven by default); also session.begin/session.end,
    vad.speech_start/vad.speech_end, error ({"code", "is_fatal", "message"})

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
WS_ENDPOINT = "wss://api.sarvam.ai/speech-to-text-realtime/ws"


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
    if sample_rate not in (8000, 16000):
        raise ValueError(f"{wav_path}: Sarvam realtime streaming only accepts 8000/16000 Hz, got {sample_rate}")

    url = (
        f"{WS_ENDPOINT}?language_code={cfg.get('language_code', 'bn-IN')}"
        f"&model={cfg.get('model', 'saaras:v3-realtime')}"
        f"&stream_type={cfg.get('stream_type', 'balanced')}"
        f"&encoding=linear16&sample_rate={sample_rate}"
    )

    first_partial_latency_s = None
    first_final_latency_s = None
    last_result_latency_s = None
    num_partial = 0
    num_final = 0
    final_segments = []
    partial_transcripts = []
    state = {"fatal_error": None, "send_done": False}

    t0 = time.perf_counter()
    with ws_client.connect(url, additional_headers={"api-subscription-key": api_key}) as ws:

        def sender():
            chunk_s = chunk_ms / 1000
            try:
                for chunk in chunks:
                    t_chunk_start = time.perf_counter()
                    ws.send(json.dumps({
                        "event": "audio_input",
                        "audio": base64.b64encode(chunk).decode("ascii"),
                    }))
                    # Pace sends to real time -- without this every chunk
                    # lands instantly and "first partial/final" latency
                    # stops meaning anything relative to a live mic feed.
                    sleep_for = chunk_s - (time.perf_counter() - t_chunk_start)
                    if sleep_for > 0:
                        time.sleep(sleep_for)
                ws.send(json.dumps({"event": "end"}))
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

            event = msg.get("event")
            if event == "transcript.partial":
                t_now = time.perf_counter() - t0
                num_partial += 1
                partial_transcripts.append({"t": round(t_now, 3), "transcript": msg.get("text", "")})
                if first_partial_latency_s is None:
                    first_partial_latency_s = t_now
                last_result_latency_s = t_now
            elif event == "transcript.final":
                t_now = time.perf_counter() - t0
                num_final += 1
                final_segments.append(msg.get("text", ""))
                if first_final_latency_s is None:
                    first_final_latency_s = t_now
                last_result_latency_s = t_now
                if state["send_done"]:
                    break
            elif event == "session.end":
                break
            elif event == "error" and msg.get("is_fatal"):
                state["fatal_error"] = f"{msg.get('code')}: {msg.get('message')}"
                break

        sender_thread.join(timeout=5)

    if state["fatal_error"]:
        raise RuntimeError(f"Sarvam realtime error {state['fatal_error']}")

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
