"""Sarvam AI Saarika speech-to-text."""
import os

import requests

ENDPOINT = "https://api.sarvam.ai/speech-to-text"


def transcribe(wav_path: str, cfg: dict) -> str:
    headers = {"api-subscription-key": os.environ[cfg["api_key_env"]]}
    data = {
        "model": cfg.get("model", "saarika:v2"),
        "language_code": cfg.get("language_code", "unknown"),
    }
    with open(wav_path, "rb") as f:
        files = {"file": (os.path.basename(wav_path), f, "audio/wav")}
        r = requests.post(ENDPOINT, headers=headers, data=data, files=files, timeout=120)
    r.raise_for_status()
    return (r.json().get("transcript") or "").strip()
