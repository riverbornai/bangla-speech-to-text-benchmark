"""Gemini-TTS via google-genai: batch = `generate_content()`, stream = `generate_content_stream()`."""

from __future__ import annotations

from runner.config import ProviderConfig
from runner.providers.gemini._common import GeminiProvider, parse_output_format
from runner.providers.gemini.batch import GeminiBatch
from runner.providers.gemini.stream import GeminiStream

__all__ = ["GeminiBatch", "GeminiProvider", "GeminiStream", "create", "parse_output_format"]


def create(config: ProviderConfig) -> GeminiProvider:
    cls = GeminiStream if config.mode == "stream" else GeminiBatch
    return cls(config)
