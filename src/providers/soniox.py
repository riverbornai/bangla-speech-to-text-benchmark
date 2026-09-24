"""
Soniox async speech-to-text.

Flow: upload file -> create transcription job -> poll -> fetch transcript.

Base URL is region-configurable (Soniox has separate US/EU hosted APIs with
different data residency). Set it via the env var named in cfg["base_url_env"]
(defaults to SONIOX_API_BASE_URL); falls back to the global endpoint if unset.
Note: this adapter uses the async REST API, not the real-time websocket
endpoint (SONIOX_STT_URL) -- batch files don't need streaming.
"""
import os
import time

import requests

DEFAULT_BASE = "https://api.soniox.com/v1"


def _base(cfg):
    env_name = cfg.get("base_url_env", "SONIOX_API_BASE_URL")
    return os.environ.get(env_name, DEFAULT_BASE).rstrip("/")


def _headers(cfg):
    return {"Authorization": "Bearer " + os.environ[cfg["api_key_env"]]}


def transcribe(wav_path: str, cfg: dict) -> str:
    base = _base(cfg)
    h = _headers(cfg)

    # 1) upload
    with open(wav_path, "rb") as f:
        up = requests.post(f"{base}/files", headers=h,
                           files={"file": (os.path.basename(wav_path), f, "audio/wav")},
                           timeout=120)
    up.raise_for_status()
    file_id = up.json()["id"]

    try:
        # 2) create transcription job
        body = {"file_id": file_id, "model": cfg.get("model", "stt-async-preview")}
        if cfg.get("language_hints"):
            body["language_hints"] = cfg["language_hints"]
        cr = requests.post(f"{base}/transcriptions", headers=h, json=body, timeout=60)
        cr.raise_for_status()
        tid = cr.json()["id"]

        # 3) poll
        for _ in range(150):
            st = requests.get(f"{base}/transcriptions/{tid}", headers=h, timeout=30).json()
            status = st.get("status")
            if status == "completed":
                break
            if status == "error":
                raise RuntimeError(f"Soniox job error: {st.get('error_message')}")
            time.sleep(2)
        else:
            raise TimeoutError("Soniox job did not complete in time")

        # 4) fetch transcript
        tr = requests.get(f"{base}/transcriptions/{tid}/transcript", headers=h, timeout=30).json()
        if tr.get("text"):
            return tr["text"].strip()
        return "".join(t.get("text", "") for t in tr.get("tokens", [])).strip()
    finally:
        # 5) cleanup uploaded file (best effort)
        try:
            requests.delete(f"{base}/files/{file_id}", headers=h, timeout=30)
        except Exception:
            pass
