"""Soniox: batch = `tts.generate()` (REST), stream = `realtime.tts.connect()` (WebSocket)."""

from __future__ import annotations

import os

from runner.config import ConfigError, ProviderConfig
from runner.providers.soniox._common import SonioxProvider, parse_output_format
from runner.providers.soniox.batch import SonioxBatch
from runner.providers.soniox.stream import SonioxStream

__all__ = ["SonioxBatch", "SonioxProvider", "SonioxStream", "create", "parse_output_format"]


def create(config: ProviderConfig) -> SonioxProvider:
    api_key = os.environ.get("SONIOX_API_KEY")
    if not api_key:
        raise ConfigError("SONIOX_API_KEY is not set (expected in .env)")
    cls = SonioxStream if config.mode == "stream" else SonioxBatch
    return cls(config, api_key)
