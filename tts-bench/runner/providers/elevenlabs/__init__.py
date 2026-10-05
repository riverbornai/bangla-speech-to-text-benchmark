"""ElevenLabs: batch = `text_to_speech.convert()`, stream = `text_to_speech.stream()`."""

from __future__ import annotations

import os

from runner.config import ConfigError, ProviderConfig
from runner.providers.elevenlabs._common import ElevenLabsProvider, parse_output_format
from runner.providers.elevenlabs.batch import ElevenLabsBatch
from runner.providers.elevenlabs.stream import ElevenLabsStream

__all__ = ["ElevenLabsBatch", "ElevenLabsProvider", "ElevenLabsStream", "create", "parse_output_format"]


def create(config: ProviderConfig) -> ElevenLabsProvider:
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        raise ConfigError("ELEVENLABS_API_KEY is not set (expected in .env)")
    cls = ElevenLabsStream if config.mode == "stream" else ElevenLabsBatch
    return cls(config, api_key)
