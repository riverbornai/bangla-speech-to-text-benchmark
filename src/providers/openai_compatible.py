"""
OpenAI-compatible /audio/transcriptions endpoint.
Covers BOTH Groq (whisper-large-v3) and OpenAI (gpt-4o-transcribe) --
they share the same request shape, only base_url + model differ.
"""
import os

from openai import OpenAI


def transcribe(wav_path: str, cfg: dict) -> str:
    client = OpenAI(
        api_key=os.environ[cfg["api_key_env"]],
        base_url=cfg.get("base_url"),
    )
    kwargs = {"model": cfg["model"], "response_format": "json"}
    if cfg.get("language"):
        kwargs["language"] = cfg["language"]
    with open(wav_path, "rb") as f:
        resp = client.audio.transcriptions.create(file=f, **kwargs)
    return (resp.text or "").strip()
