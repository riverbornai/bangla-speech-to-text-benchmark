"""Sarvam: batch = `text_to_speech.convert()`, stream = `text_to_speech.convert_stream()`."""

from __future__ import annotations

import os

from runner.config import ConfigError, ProviderConfig
from runner.providers.sarvam._common import SarvamProvider, parse_output_format
from runner.providers.sarvam.batch import SarvamBatch
from runner.providers.sarvam.stream import SarvamStream

__all__ = ["SarvamBatch", "SarvamProvider", "SarvamStream", "create", "parse_output_format"]


def create(config: ProviderConfig) -> SarvamProvider:
    api_key = os.environ.get("SARVAM_API_KEY")
    if not api_key:
        raise ConfigError("SARVAM_API_KEY is not set (expected in .env)")
    cls = SarvamStream if config.mode == "stream" else SarvamBatch
    return cls(config, api_key)
