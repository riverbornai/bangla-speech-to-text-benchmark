"""
Deepgram Nova-3 -- streaming benchmark adapter.

Protocol verified against Deepgram's published AsyncAPI spec:
https://developers.deepgram.com/reference/speech-to-text/listen-streaming

  - wss://api.deepgram.com/v1/listen
    ?model=<model>&language=<code>&encoding=linear16&sample_rate=<sr>
    &channels=<n>&interim_results=true&smart_format=<bool>
  - auth via the `Authorization: Token <key>` header (same header as the
    batch REST endpoint in deepgram.py)
  - client sends raw 16-bit PCM mono audio as BINARY WebSocket frames
    (not JSON-wrapped, unlike the Sarvam/ElevenLabs adapters), paced in
    real time, then a JSON control message {"type": "CloseStream"} to
    finalize and close
  - server sends {"type": "Results", "is_final": bool, "speech_final": bool,
    "channel": {"alternatives": [{"transcript": "..."}]}}; a standalone
    {"type": "Metadata", ...} summarizing the whole session is sent once,
    right before the connection closes, after CloseStream is processed --
    used here as the completion signal

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
WS_ENDPOINT = "wss://api.deepgram.com/v1/listen"


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
    api_key = os.environ[cfg["api_key_env"]]
    chunk_ms = cfg.get("chunk_ms", DEFAULT_CHUNK_MS)

    chunks, sample_rate, channels, sampwidth, audio_duration_s = _read_pcm_chunks(wav_path, chunk_ms)
    if sampwidth != 2:
        raise ValueError(f"{wav_path}: expected 16-bit PCM wav, got {sampwidth * 8}-bit")

    smart_format = "true" if cfg.get("smart_format", True) else "false"
    url = (
        f"{WS_ENDPOINT}?model={cfg.get('model', 'nova-3')}"
        f"&language={cfg.get('language', 'bn')}"
        f"&encoding=linear16&sample_rate={sample_rate}&channels={channels}"
        f"&interim_results=true&smart_format={smart_format}"
    )

    first_partial_latency_s = None
    first_final_latency_s = None
    last_result_latency_s = None
    num_partial = 0
    num_final = 0
    final_segments = []
    partial_transcripts = []
    state = {"send_done": False}

    t0 = time.perf_counter()
    with ws_client.connect(url, additional_headers={"Authorization": "Token " + api_key}) as ws:

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
                ws.send(json.dumps({"type": "CloseStream"}))
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

            mtype = msg.get("type")
            if mtype == "Results":
                alternatives = msg.get("channel", {}).get("alternatives", [{}])
                transcript = (alternatives[0].get("transcript") if alternatives else "") or ""
                if not transcript:
                    continue  # Deepgram sends empty-transcript Results during silence
                t_now = time.perf_counter() - t0
                if msg.get("is_final"):
                    num_final += 1
                    final_segments.append(transcript)
                    if first_final_latency_s is None:
                        first_final_latency_s = t_now
                else:
                    num_partial += 1
                    partial_transcripts.append({"t": round(t_now, 3), "transcript": transcript})
                    if first_partial_latency_s is None:
                        first_partial_latency_s = t_now
                last_result_latency_s = t_now
            elif mtype == "Metadata" and state["send_done"]:
                break
            # SpeechStarted / UtteranceEnd: not used for these metrics

        sender_thread.join(timeout=5)

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
