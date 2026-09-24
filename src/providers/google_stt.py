"""
Google Cloud Speech-to-Text v2 with the Chirp 2 model.

Uses synchronous recognize with inline audio -- fine for BanSpeech's short,
pre-segmented utterances. Auth via Application Default Credentials
(GOOGLE_APPLICATION_CREDENTIALS pointing at a service-account JSON).
"""
import os

from google.cloud import speech_v2
from google.cloud.speech_v2.types import cloud_speech


def transcribe(wav_path: str, cfg: dict) -> str:
    project = os.environ[cfg["project_env"]]
    location = cfg.get("location", "us-central1")

    client = speech_v2.SpeechClient(
        client_options={"api_endpoint": f"{location}-speech.googleapis.com"}
    )
    with open(wav_path, "rb") as f:
        content = f.read()

    config = cloud_speech.RecognitionConfig(
        auto_decoding_config=cloud_speech.AutoDetectDecodingConfig(),
        language_codes=[cfg.get("language_code", "bn-BD")],
        model=cfg.get("model", "chirp_2"),
    )
    request = cloud_speech.RecognizeRequest(
        recognizer=f"projects/{project}/locations/{location}/recognizers/_",
        config=config,
        content=content,
    )
    resp = client.recognize(request=request)

    return " ".join(
        r.alternatives[0].transcript for r in resp.results if r.alternatives
    ).strip()
