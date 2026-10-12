"""Cartesia Sonic: batch = `tts.generate()`, stream = `tts.generate_sse()`."""

from __future__ import annotations

import base64
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from runner.config import ConfigError, ProviderConfig
from runner.dataset import DatasetItem
from runner.providers.base import (
    Mode,
    ProviderError,
    SynthesisResult,
    collect_chunks,
    pcm_to_wav,
)

TIMEOUT_S = 120


def parse_output_format(output_format: str) -> tuple[str, int]:
    """'wav_24000' -> ('wav', 24000); 'pcm_24000' -> ('pcm', 24000)."""
    codec, _, rate = output_format.partition("_")
    if codec not in ("wav", "pcm") or not rate.isdigit():
        raise ConfigError(
            f"cartesia: unsupported output format {output_format!r} (only wav_<rate>, pcm_<rate>)"
        )
    return codec, int(rate)


def _error_code(body: object, status: int | None) -> str:
    # Only the provider's short error code; never the message or the rest of the body.
    if isinstance(body, dict) and body.get("error_code"):
        return str(body["error_code"])[:100]
    return f"http_{status}"


def _request_id(body: object) -> str | None:
    return str(body["request_id"]) if isinstance(body, dict) and body.get("request_id") else None


@contextmanager
def sdk_errors() -> Iterator[None]:
    from cartesia import APIConnectionError, APIStatusError

    try:
        yield
    except APIStatusError as e:
        raise ProviderError(
            e.status_code,
            _error_code(e.body, e.status_code),
            _request_id(e.body),
        ) from e
    except APIConnectionError as e:  # includes APITimeoutError
        raise ProviderError(None, type(e).__name__) from e


class CartesiaProvider:
    """Shared by both modes; subclasses implement `synthesize`."""

    name = "cartesia"
    mode: Mode
    format = "wav"  # stored as WAV in both modes (stream wraps raw PCM)

    def __init__(self, config: ProviderConfig, api_key: str) -> None:
        from cartesia import Cartesia

        self.config = config
        self.codec, self.sample_rate = parse_output_format(config.output_format)
        # The SDK sends `Cartesia-Version` itself. max_retries=0: every request is timed exactly once.
        self._client = Cartesia(api_key=api_key, max_retries=0, timeout=TIMEOUT_S)

    def supports(self, item: DatasetItem) -> bool:
        return self.config.max_chars is None or len(item.text) <= self.config.max_chars

    def _params(self, text: str, container: str) -> dict[str, Any]:
        # Default speed/emotion (baseline): only the transcript, voice, language and format are sent.
        return {
            "model_id": self.config.model,
            "transcript": text,
            "voice": {"mode": "id", "id": self.config.voice.id},
            "language": self.config.language_code,  # `language`, never also `locale`
            "output_format": {
                "container": container,
                "encoding": "pcm_s16le",
                "sample_rate": self.sample_rate,
            },
        }

    def close(self) -> None:
        self._client.close()


class CartesiaBatch(CartesiaProvider):
    """`tts.generate()` -> POST /tts/bytes: the clip is rendered, then sent as a WAV."""

    mode = "batch"

    def synthesize(self, text: str) -> SynthesisResult:
        start = time.perf_counter_ns()
        with sdk_errors():
            audio = self._client.tts.generate(**self._params(text, "wav")).read()
        total_ms = (time.perf_counter_ns() - start) / 1e6
        if not audio:
            raise ProviderError(200, "empty_audio")
        return SynthesisResult(
            audio=audio,
            format=self.format,
            sample_rate=self.sample_rate,
            ttfb_ms=None,  # batch: the whole clip arrives in one body
            total_ms=total_ms,
            billed_chars=len(text),
            request_id=None,  # no request-id response header is documented for successes
        )


class CartesiaStream(CartesiaProvider):
    """`tts.generate_sse()` -> POST /tts/sse: base64 PCM chunks while the model renders.

    SSE documents only raw encodings, so this asks for `raw` pcm_s16le and wraps it as WAV at the end.
    """

    mode = "stream"

    def _chunks(self, text: str) -> Iterator[bytes]:
        for event in self._client.tts.generate_sse(**self._params(text, "raw")):
            if event.type == "chunk":
                yield base64.b64decode(event.data or "")
            elif event.type == "error":
                # In-band error: keep only the short code, never the message.
                raise ProviderError(
                    event.status_code,
                    str(event.error_code or f"http_{event.status_code}")[:100],
                    event.request_id,
                )

    def synthesize(self, text: str) -> SynthesisResult:
        start = time.perf_counter_ns()
        with sdk_errors():
            pcm, ttfb_ms, total_ms = collect_chunks(start, self._chunks(text))
        return SynthesisResult(
            audio=pcm_to_wav(pcm, self.sample_rate),
            format=self.format,
            sample_rate=self.sample_rate,
            ttfb_ms=ttfb_ms,
            total_ms=total_ms,
            billed_chars=len(text),
            request_id=None,  # chunk events carry a context_id, not a request id
        )


__all__ = ["CartesiaBatch", "CartesiaProvider", "CartesiaStream", "create", "parse_output_format"]


def create(config: ProviderConfig) -> CartesiaProvider:
    api_key = os.environ.get("CARTESIA_API_KEY")
    if not api_key:
        raise ConfigError("CARTESIA_API_KEY is not set (expected in .env)")
    cls = CartesiaStream if config.mode == "stream" else CartesiaBatch
    return cls(config, api_key)
