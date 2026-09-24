"""
Soniox real-time speech-to-text -- streaming benchmark adapter.

Protocol verified against Soniox's own reference implementation
(speech_to_text/python/soniox_realtime.py in
https://github.com/soniox/soniox_examples), not just prose docs:

  - wss://stt-rt.soniox.com/transcribe-websocket
  - auth is NOT a header -- the API key goes inside the first JSON config
    message: {"api_key": "...", "model": "stt-rt-v5", "audio_format":
    "pcm_s16le", "sample_rate": 16000, "num_channels": 1,
    "language_hints": [...], "enable_endpoint_detection": true}
  - client then sends raw 16-bit PCM mono audio as BINARY WebSocket frames
    (no JSON envelope), paced in real time, then an EMPTY STRING message
    ("") to signal end-of-audio
  - server sends {"tokens": [{"text": "...", "is_final": bool, ...}],
    "finished": bool} repeatedly. Semantics differ from every other
    adapter here: `is_final` is per TOKEN, not per message or per
    utterance. Final tokens are each returned exactly once and accumulate;
    non-final tokens are the model's CURRENT full partial hypothesis and
    are replaced (not appended) on every message. Session ends when
    "finished": true arrives, or on {"error_code", "error_message"}.
    Token text is concatenated directly (no separator) -- spacing is its
    own token in the stream, unlike space-joined transcripts elsewhere.
    `enable_endpoint_detection` also makes the server emit a sentinel
    {"text": "<end>", "is_final": true} token marking each finalized
    segment boundary -- it's a control signal for downstream logic, not
    transcript text, so it's excluded from the transcript below (it still
    counts as a finalization event for timing purposes).

Note the different model family from the batch adapter: `stt-rt-v5` here
vs. `stt-async-v5` (soniox.py) -- "rt" (real-time) and "async" (batch) are
separate model lines, not the same model used two ways.

Send and receive run on separate threads (a sync `websockets` connection
supports concurrent send/recv) so partial/final timestamps reflect when
the server actually emitted them, not when we got around to reading the
socket after finishing the send loop.
"""
import json
import os
import threading
import time
import wave

import websockets
import websockets.sync.client as ws_client

DEFAULT_CHUNK_MS = 100
WS_ENDPOINT = "wss://stt-rt.eu.soniox.com/transcribe-websocket"


def _read_pcm_chunks(wav_path: str, chunk_ms: int):
    with wave.open(wav_path, "rb") as w:
        sample_rate = w.getframerate()
        channels = w.getnchannels()
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
    return chunks, sample_rate, channels, sampwidth, duration_s


def stream_transcribe(wav_path: str, cfg: dict) -> dict:
    api_key = os.environ[cfg["api_key_env"]].strip()
    chunk_ms = cfg.get("chunk_ms", DEFAULT_CHUNK_MS)

    chunks, sample_rate, channels, sampwidth, audio_duration_s = _read_pcm_chunks(wav_path, chunk_ms)
    if sampwidth != 2:
        raise ValueError(f"{wav_path}: expected 16-bit PCM wav, got {sampwidth * 8}-bit")

    config = {
        "api_key": api_key,
        "model": cfg.get("model", "stt-rt-v5"),
        "audio_format": "pcm_s16le",
        "sample_rate": sample_rate,
        "num_channels": channels,
        "enable_endpoint_detection": True,
    }
    if cfg.get("language_hints"):
        config["language_hints"] = cfg["language_hints"]

    first_partial_latency_s = None
    first_final_latency_s = None
    last_result_latency_s = None
    num_partial = 0
    num_final = 0
    final_tokens_text = []
    partial_transcripts = []
    state = {"send_done": False, "fatal_error": None}

    t0 = time.perf_counter()
    with ws_client.connect(WS_ENDPOINT) as ws:
        ws.send(json.dumps(config))

        def sender():
            chunk_s = chunk_ms / 1000
            try:
                for chunk in chunks:
                    t_chunk_start = time.perf_counter()
                    ws.send(chunk)  # raw binary frame -- no JSON envelope
                    # Pace sends to real time -- without this every chunk
                    # lands instantly and "first partial/final" latency
                    # stops meaning anything relative to a live mic feed.
                    sleep_for = chunk_s - (time.perf_counter() - t_chunk_start)
                    if sleep_for > 0:
                        time.sleep(sleep_for)
                ws.send("")  # empty string signals end-of-audio
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
                if state["send_done"]:
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

            if msg.get("error_code") is not None:
                state["fatal_error"] = f"{msg.get('error_code')}: {msg.get('error_message')}"
                break

            t_now = time.perf_counter() - t0
            non_final_texts = []
            got_new_final = False
            for token in msg.get("tokens", []):
                text = token.get("text")
                if not text:
                    continue
                if text == "<end>":
                    # Sentinel emitted by enable_endpoint_detection to mark a
                    # finalized segment boundary -- always final, but a
                    # control signal, not transcript text.
                    got_new_final = True
                    continue
                if token.get("is_final"):
                    final_tokens_text.append(text)
                    got_new_final = True
                else:
                    non_final_texts.append(text)

            if got_new_final:
                num_final += 1
                if first_final_latency_s is None:
                    first_final_latency_s = t_now
                last_result_latency_s = t_now
            if non_final_texts:
                num_partial += 1
                partial_transcripts.append({"t": round(t_now, 3), "transcript": "".join(non_final_texts)})
                if first_partial_latency_s is None:
                    first_partial_latency_s = t_now
                last_result_latency_s = t_now

            if msg.get("finished"):
                break

        sender_thread.join(timeout=5)

    if state["fatal_error"]:
        raise RuntimeError(f"Soniox realtime error {state['fatal_error']}")

    total_latency_s = time.perf_counter() - t0
    transcript = "".join(final_tokens_text).strip()
    if not transcript and partial_transcripts:
        # Session ended without a finalized token (shouldn't happen with
        # endpoint detection on, but fall back to the last partial snapshot).
        transcript = partial_transcripts[-1]["transcript"].strip()

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
