"""Sarvam: batch = `text_to_speech.convert()`, stream = `text_to_speech.convert_stream()`."""

from __future__ import annotations

import base64
import binascii
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import httpx

from runner.config import ConfigError, ProviderConfig
from runner.dataset import DatasetItem
from runner.providers.base import Mode, ProviderError, SynthesisResult, collect_chunks, to_wav

REQUEST_OPTIONS = {
    "timeout_in_seconds": 120,
    "max_retries": 0,
}  # no retries: a failed request is recorded as an error


def parse_output_format(output_format: str) -> tuple[str, int]:
    """'wav_24000' -> ('wav', 24000); 'mp3_24000' -> ('mp3', 24000)."""
    codec, _, rate = output_format.partition("_")
    if codec not in ("wav", "mp3", "flac") or not rate.isdigit():
        raise ConfigError(f"sarvam: unsupported output format {output_format!r}")
    return codec, int(rate)


def _error_code(body: object, status: int | None) -> str:
    # Only the provider's short error code; never the full body.
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        return str(body["error"].get("code") or "error")[:100]
    return f"http_{status}"


@contextmanager
def sdk_errors() -> Iterator[None]:
    from sarvamai.core.api_error import ApiError

    try:
        yield
    except ApiError as e:
        headers = e.headers or {}
        raise ProviderError(
            e.status_code,
            _error_code(e.body, e.status_code),
            headers.get("request-id"),
        ) from e
    except httpx.TransportError as e:
        raise ProviderError(None, type(e).__name__) from e


class SarvamProvider:
    """Shared by both modes; subclasses implement `synthesize`."""

    name = "sarvam"
    mode: Mode

    def __init__(self, config: ProviderConfig, api_key: str) -> None:
        from sarvamai import SarvamAI

        self.config = config
        self.format, self.sample_rate = parse_output_format(config.output_format)
        self._client = SarvamAI(api_subscription_key=api_key)

    def supports(self, item: DatasetItem) -> bool:
        return self.config.max_chars is None or len(item.text) <= self.config.max_chars

    def _params(self, text: str) -> dict[str, Any]:
        return {
            "text": text,
            "language_code": self.config.language_code,
            "model": self.config.model,
            "speaker": self.config.voice.id,
            "output_audio_codec": self.format,
            "speech_sample_rate": self.sample_rate,
            "request_options": REQUEST_OPTIONS,
            "temperature": 0.02,
            **(self.config.voice_settings or {}),
        }

    def close(self) -> None:
        pass


class SarvamBatch(SarvamProvider):
    """`text_to_speech.convert()` -> POST /text-to-speech: one JSON body with base64 audio."""

    mode = "batch"

    def synthesize(self, text: str) -> SynthesisResult:
        start = time.perf_counter_ns()
        with sdk_errors():
            resp = self._client.text_to_speech.convert(**self._params(text))
        total_ms = (time.perf_counter_ns() - start) / 1e6

        audios = resp.audios or []
        if len(audios) != 1:
            raise ProviderError(200, f"expected 1 audio, got {len(audios)}", resp.request_id)
        try:
            audio = base64.b64decode(audios[0], validate=True)
        except binascii.Error as e:
            raise ProviderError(200, "bad_base64", resp.request_id) from e
        if not audio:
            raise ProviderError(200, "empty_audio", resp.request_id)
        return SynthesisResult(
            audio=to_wav(audio, self.sample_rate),  # re-wrap: the header's data length can be a placeholder
            format=self.format,
            sample_rate=self.sample_rate,
            ttfb_ms=None,  # batch: the whole clip arrives in one JSON body
            total_ms=total_ms,
            billed_chars=len(text),
            request_id=resp.request_id,
        )


class SarvamStream(SarvamProvider):
    """`text_to_speech.convert_stream()` -> POST /text-to-speech/stream: raw audio bytes as they render."""

    mode = "stream"

    def synthesize(self, text: str) -> SynthesisResult:
        start = time.perf_counter_ns()
        with sdk_errors():
            audio, ttfb_ms, total_ms = collect_chunks(
                start, self._client.text_to_speech.convert_stream(**self._params(text))
            )
        return SynthesisResult(
            audio=to_wav(audio, self.sample_rate),
            format=self.format,
            sample_rate=self.sample_rate,
            ttfb_ms=ttfb_ms,
            total_ms=total_ms,
            billed_chars=len(text),
            request_id=None,  # the stream iterator doesn't expose response headers
        )


__all__ = ["SarvamBatch", "SarvamProvider", "SarvamStream", "create", "parse_output_format"]


def create(config: ProviderConfig) -> SarvamProvider:
    api_key = os.environ.get("SARVAM_API_KEY")
    if not api_key:
        raise ConfigError("SARVAM_API_KEY is not set (expected in .env)")
    cls = SarvamStream if config.mode == "stream" else SarvamBatch
    return cls(config, api_key)
