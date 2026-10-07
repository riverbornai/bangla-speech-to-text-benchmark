from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import httpx

from runner.config import ConfigError, ProviderConfig
from runner.dataset import DatasetItem
from runner.providers.base import Mode, ProviderError, SynthesisResult, collect_chunks, with_retries

REQUEST_OPTIONS = {"timeout_in_seconds": 120, "max_retries": 0}  # retries handled by with_retries


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
        retry_after = headers.get("retry-after")
        raise ProviderError(
            e.status_code,
            _error_code(e.body, e.status_code),
            headers.get("request-id"),
            float(retry_after) if retry_after and retry_after.isdigit() else None,
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

    def _attempt(self, text: str) -> SynthesisResult:
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
            attempts=1,
        )

    def synthesize(self, text: str) -> SynthesisResult:
        result, attempts = with_retries(lambda: self._attempt(text))
        return SynthesisResult(**{**result.__dict__, "attempts": attempts})

    def close(self) -> None:
        pass
