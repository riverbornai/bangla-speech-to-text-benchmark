"""Cartesia Sonic: batch = `tts.generate()`, stream = `tts.generate_sse()`."""

from __future__ import annotations

import os

from runner.config import ConfigError, ProviderConfig
from runner.providers.cartesia._common import CartesiaProvider, parse_output_format
from runner.providers.cartesia.batch import CartesiaBatch
from runner.providers.cartesia.stream import CartesiaStream

__all__ = ["CartesiaBatch", "CartesiaProvider", "CartesiaStream", "create", "parse_output_format"]


def create(config: ProviderConfig) -> CartesiaProvider:
    api_key = os.environ.get("CARTESIA_API_KEY")
    if not api_key:
        raise ConfigError("CARTESIA_API_KEY is not set (expected in .env)")
    cls = CartesiaStream if config.mode == "stream" else CartesiaBatch
    return cls(config, api_key)
