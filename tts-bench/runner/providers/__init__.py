from __future__ import annotations

import importlib

from runner.config import ProviderConfig
from runner.providers.base import TTSProvider

# Imported lazily so one broken SDK doesn't break every provider.
_REGISTRY = {
    "cartesia": "runner.providers.cartesia",
    "elevenlabs": "runner.providers.elevenlabs",
    "gemini": "runner.providers.gemini",
    "openai": "runner.providers.openai_tts",  # package name avoids clashing with the `openai` SDK
    "sarvam": "runner.providers.sarvam",
    "soniox": "runner.providers.soniox",
}


def create_provider(config: ProviderConfig) -> TTSProvider:
    if config.name not in _REGISTRY:
        raise ValueError(f"no provider module for {config.name!r}; have {sorted(_REGISTRY)}")
    return importlib.import_module(_REGISTRY[config.name]).create(config)
