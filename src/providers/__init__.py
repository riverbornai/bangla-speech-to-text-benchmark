"""
Provider registry.

Batch adapters expose:      transcribe(wav_path: str, cfg: dict) -> str
Streaming adapters expose:  stream_transcribe(wav_path: str, cfg: dict) -> dict
                             (dict includes transcript + latency/stability metrics)
Selected by the `type` field in config.yaml -- see run_transcription.py for
batch and run_streaming_transcription.py for streaming.
"""
from . import (
    openai_compatible,
    openai_realtime_streaming,
    sarvam,
    sarvam_streaming,
    elevenlabs,
    elevenlabs_streaming,
    deepgram,
    deepgram_streaming,
    soniox,
    soniox_streaming,
    google_stt,
    google_stt_streaming,
    gemini,
    gemini_streaming,
)

REGISTRY = {
    "openai_compatible": openai_compatible.transcribe,
    "sarvam": sarvam.transcribe,
    "elevenlabs": elevenlabs.transcribe,
    "deepgram": deepgram.transcribe,
    "soniox": soniox.transcribe,
    "google_stt": google_stt.transcribe,
    "gemini": gemini.transcribe,
}

STREAMING_REGISTRY = {
    "google_stt_streaming": google_stt_streaming.stream_transcribe,
    "sarvam_streaming": sarvam_streaming.stream_transcribe,
    "openai_realtime_streaming": openai_realtime_streaming.stream_transcribe,
    "elevenlabs_streaming": elevenlabs_streaming.stream_transcribe,
    "gemini_streaming": gemini_streaming.stream_transcribe,
    "deepgram_streaming": deepgram_streaming.stream_transcribe,
    "soniox_streaming": soniox_streaming.stream_transcribe,
}


def get(provider_type: str):
    if provider_type not in REGISTRY:
        raise KeyError(f"Unknown provider type: {provider_type}")
    return REGISTRY[provider_type]


def get_streaming(provider_type: str):
    if provider_type not in STREAMING_REGISTRY:
        raise KeyError(f"Unknown streaming provider type: {provider_type}")
    return STREAMING_REGISTRY[provider_type]
