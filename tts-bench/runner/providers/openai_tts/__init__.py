"""OpenAI TTS: batch = `audio.speech.create()`, stream = `audio.speech.with_streaming_response.create()`."""

from __future__ import annotations

import os

from runner.config import ConfigError, ProviderConfig
from runner.providers.openai_tts._common import OpenAITTSProvider, parse_output_format
from runner.providers.openai_tts.batch import OpenAIBatch
from runner.providers.openai_tts.stream import OpenAIStream

__all__ = ["OpenAIBatch", "OpenAIStream", "OpenAITTSProvider", "create", "parse_output_format"]


def create(config: ProviderConfig) -> OpenAITTSProvider:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ConfigError("OPENAI_API_KEY is not set (expected in .env)")
    cls = OpenAIStream if config.mode == "stream" else OpenAIBatch
    return cls(config, api_key)
