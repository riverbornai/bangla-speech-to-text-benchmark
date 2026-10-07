from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from runner.config import ConfigError, ProviderConfig
from runner.dataset import DatasetItem
from runner.providers.base import Mode, ProviderError, SynthesisResult, pcm_to_wav, with_retries

TIMEOUT_S = 120
REQUEST_ID_HEADER = "x-request-id"


def parse_output_format(output_format: str) -> tuple[str, int]:
    """'wav_24000' -> ('wav', 24000); 'pcm_24000' -> ('pcm', 24000). The API returns 24 kHz for both."""
    codec, _, rate = output_format.partition("_")
    if codec not in ("wav", "pcm") or not rate.isdigit():
        raise ConfigError(
            f"openai: unsupported output format {output_format!r} (only wav_<rate> / pcm_<rate>)"
        )
    return codec, int(rate)


def _error_code(body: object, status: int | None) -> str:
    # Only the provider's short error code; never the message or the full body.
    if isinstance(body, dict):
        inner = body.get("error") if isinstance(body.get("error"), dict) else body
        code = inner.get("code") or inner.get("type")
        if code:
            return str(code)[:100]
    return f"http_{status}"


def _retry_after(value: str | None) -> float | None:
    try:
        return float(value) if value else None
    except ValueError:
        return None


@contextmanager
def sdk_errors() -> Iterator[None]:
    import openai

    try:
        yield
    except openai.APIStatusError as e:
        headers = e.response.headers
        raise ProviderError(
            e.status_code,
            _error_code(e.body, e.status_code),
            e.request_id or headers.get(REQUEST_ID_HEADER),
            _retry_after(headers.get("retry-after")),
        ) from e
    except openai.APIConnectionError as e:  # includes APITimeoutError
        raise ProviderError(None, type(e).__name__) from e


class OpenAITTSProvider:
    """Shared by both modes; subclasses implement `_attempt`."""

    name = "openai"
    mode: Mode
    format = "wav"  # the clip is always stored as WAV, whatever response_format was requested

    def __init__(self, config: ProviderConfig, api_key: str) -> None:
        from openai import OpenAI

        if config.voice_settings:
            raise ConfigError("openai: voice_settings are not supported (baseline sends no `instructions`)")
        self.config = config
        self._codec, self.sample_rate = parse_output_format(config.output_format)
        # The SDK's own retries are off: with_retries owns backoff, so every attempt is timed and counted.
        self._client = OpenAI(api_key=api_key, max_retries=0, timeout=TIMEOUT_S)

    def supports(self, item: DatasetItem) -> bool:
        return self.config.max_chars is None or len(item.text) <= self.config.max_chars

    def _params(self, text: str) -> dict[str, Any]:
        # No language parameter (the model infers it) and no `instructions`: defaults only.
        return {
            "model": self.config.model,
            "voice": self.config.voice.id,
            "input": text,
            "response_format": self._codec,
        }

    def _wav(self, audio: bytes) -> bytes:
        return pcm_to_wav(audio, self.sample_rate) if self._codec == "pcm" else audio

    def _result(
        self, audio: bytes, text: str, ttfb_ms: float | None, total_ms: float, request_id: str | None
    ) -> SynthesisResult:
        return SynthesisResult(
            audio=self._wav(audio),
            format=self.format,
            sample_rate=self.sample_rate,
            ttfb_ms=ttfb_ms,
            total_ms=total_ms,
            billed_chars=len(text),
            request_id=request_id or None,
            attempts=1,
        )

    def _attempt(self, text: str) -> SynthesisResult:
        raise NotImplementedError

    def synthesize(self, text: str) -> SynthesisResult:
        result, attempts = with_retries(lambda: self._attempt(text))
        return SynthesisResult(**{**result.__dict__, "attempts": attempts})

    def close(self) -> None:
        self._client.close()
