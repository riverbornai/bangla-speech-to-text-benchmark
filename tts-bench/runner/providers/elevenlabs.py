"""ElevenLabs: batch = `text_to_speech.convert()`, stream = `text_to_speech.stream()`."""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import httpx

from runner.config import ConfigError, ProviderConfig
from runner.dataset import DatasetItem
from runner.providers.base import Mode, ProviderError, SynthesisResult, collect_chunks

REQUEST_OPTIONS = {
    "timeout_in_seconds": 120,
    "max_retries": 0,
}  # no retries: a failed request is recorded as an error


def parse_output_format(output_format: str) -> tuple[str, int]:
    """'mp3_44100_128' -> ('mp3', 44100); 'pcm_24000' -> ('pcm', 24000)."""
    codec, _, rest = output_format.partition("_")
    if codec not in ("mp3", "pcm", "wav") or not rest:
        raise ConfigError(f"elevenlabs: unsupported output format {output_format!r}")
    return codec, int(rest.split("_")[0])


def _error_code(body: object, status: int | None) -> str:
    # Only the provider's short error code; never the full body.
    if isinstance(body, dict) and isinstance(body.get("detail"), dict):
        detail = body["detail"]
        return str(detail.get("status") or detail.get("code") or "error")[:100]
    return f"http_{status}"


@contextmanager
def sdk_errors() -> Iterator[None]:
    from elevenlabs.core.api_error import ApiError

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


class ElevenLabsProvider:
    """Shared by both modes; subclasses pick the SDK method in `_request`."""

    name = "elevenlabs"
    mode: Mode

    def __init__(self, config: ProviderConfig, api_key: str) -> None:
        from elevenlabs import VoiceSettings
        from elevenlabs.client import ElevenLabs

        self.config = config
        self.format, self.sample_rate = parse_output_format(config.output_format)
        self._client = ElevenLabs(api_key=api_key)
        self._voice_settings = VoiceSettings(**config.voice_settings) if config.voice_settings else None

    def supports(self, item: DatasetItem) -> bool:
        return self.config.max_chars is None or len(item.text) <= self.config.max_chars

    def _request(self, **kwargs: Any) -> Iterator[bytes]:
        raise NotImplementedError

    def synthesize(self, text: str) -> SynthesisResult:
        start = time.perf_counter_ns()
        with sdk_errors():
            audio, ttfb_ms, total_ms = collect_chunks(
                start,
                self._request(
                    voice_id=self.config.voice.id,
                    text=text,
                    model_id=self.config.model,
                    language_code=self.config.language_code,
                    output_format=self.config.output_format,
                    voice_settings=self._voice_settings,
                    request_options=REQUEST_OPTIONS,
                ),
            )
        return SynthesisResult(
            audio=audio,
            format=self.format,
            sample_rate=self.sample_rate,
            ttfb_ms=ttfb_ms if self.mode == "stream" else None,  # batch: first byte ~ last byte
            total_ms=total_ms,
            billed_chars=len(text),
            request_id=None,
        )

    def close(self) -> None:
        pass


class ElevenLabsBatch(ElevenLabsProvider):
    """`text_to_speech.convert()` -> POST /v1/text-to-speech/{voice_id}: the clip is rendered, then sent."""

    mode = "batch"

    def _request(self, **kwargs: Any) -> Iterator[bytes]:
        return self._client.text_to_speech.convert(**kwargs)


class ElevenLabsStream(ElevenLabsProvider):
    """`text_to_speech.stream()` -> POST /v1/text-to-speech/{voice_id}/stream: audio arrives as it renders."""

    mode = "stream"

    def _request(self, **kwargs: Any) -> Iterator[bytes]:
        return self._client.text_to_speech.stream(**kwargs)


__all__ = ["ElevenLabsBatch", "ElevenLabsProvider", "ElevenLabsStream", "create", "parse_output_format"]


def create(config: ProviderConfig) -> ElevenLabsProvider:
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        raise ConfigError("ELEVENLABS_API_KEY is not set (expected in .env)")
    cls = ElevenLabsStream if config.mode == "stream" else ElevenLabsBatch
    return cls(config, api_key)
