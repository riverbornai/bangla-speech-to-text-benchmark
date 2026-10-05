from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import httpx

from runner.config import ConfigError, ProviderConfig
from runner.dataset import DatasetItem
from runner.providers.base import Mode, ProviderError, SynthesisResult, with_retries

REQUEST_OPTIONS = {"timeout_in_seconds": 120, "max_retries": 0}  # retries handled by with_retries


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
        retry_after = headers.get("retry-after")
        raise ProviderError(
            e.status_code,
            _error_code(e.body, e.status_code),
            headers.get("request-id"),
            float(retry_after) if retry_after and retry_after.isdigit() else None,
        ) from e
    except httpx.TransportError as e:
        raise ProviderError(None, type(e).__name__) from e


class SarvamProvider:
    """Shared by both modes; subclasses implement `_attempt`."""

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
            **(self.config.voice_settings or {}),
        }

    def _attempt(self, text: str) -> SynthesisResult:
        raise NotImplementedError

    def synthesize(self, text: str) -> SynthesisResult:
        result, attempts = with_retries(lambda: self._attempt(text))
        return SynthesisResult(**{**result.__dict__, "attempts": attempts})

    def close(self) -> None:
        pass
