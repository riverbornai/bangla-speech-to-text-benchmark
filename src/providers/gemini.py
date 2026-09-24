"""Gemini 2.5 audio transcription via the google-genai SDK."""
import os

from google import genai
from google.genai import types

PROMPT = (
    "Transcribe this Bengali (Bangla) audio verbatim. "
    "Output ONLY the transcription in Bangla script. "
    "Do not translate, summarize, add punctuation notes, timestamps, "
    "speaker labels, or any commentary."
)


def transcribe(wav_path: str, cfg: dict) -> str:
    client = genai.Client(api_key=os.environ[cfg["api_key_env"]])
    with open(wav_path, "rb") as f:
        data = f.read()
    resp = client.models.generate_content(
        model=cfg.get("model", "gemini-2.5-flash"),
        contents=[
            PROMPT,
            types.Part.from_bytes(data=data, mime_type="audio/wav"),
        ],
    )
    return (resp.text or "").strip()
