"""ElevenLabs Scribe speech-to-text."""
import os

import requests

ENDPOINT = "https://api.elevenlabs.io/v1/speech-to-text"


def transcribe(wav_path: str, cfg: dict) -> str:
    headers = {"xi-api-key": os.environ[cfg["api_key_env"]]}
    data = {"model_id": cfg.get("model_id", "scribe_v1")}
    if cfg.get("language_code"):
        data["language_code"] = cfg["language_code"]
    with open(wav_path, "rb") as f:
        files = {"file": (os.path.basename(wav_path), f, "audio/wav")}
        r = requests.post(ENDPOINT, headers=headers, data=data, files=files, timeout=120)
    r.raise_for_status()
    return (r.json().get("text") or "").strip()
