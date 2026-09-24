"""Deepgram pre-recorded speech-to-text (Nova-3 multilingual)."""
import os

import requests

ENDPOINT = "https://api.deepgram.com/v1/listen"


def transcribe(wav_path: str, cfg: dict) -> str:
    headers = {
        "Authorization": "Token " + os.environ[cfg["api_key_env"]],
        "Content-Type": "audio/wav",
    }
    params = {
        "model": cfg.get("model", "nova-3"),
        "language": cfg.get("language", "bn"),
        "smart_format": "true",
    }
    with open(wav_path, "rb") as f:
        r = requests.post(ENDPOINT, headers=headers, params=params, data=f, timeout=120)
    r.raise_for_status()
    alt = r.json()["results"]["channels"][0]["alternatives"][0]
    return (alt.get("transcript") or "").strip()
