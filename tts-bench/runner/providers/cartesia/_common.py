from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from runner.config import ConfigError, ProviderConfig
from runner.dataset import DatasetItem
from runner.providers.base import Mode, ProviderError, SynthesisResult, with_retries

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
        retry_after = e.response.headers.get("retry-after")
        raise ProviderError(
            e.status_code,
            _error_code(e.body, e.status_code),
            _request_id(e.body),
            float(retry_after) if retry_after and retry_after.isdigit() else None,
        ) from e
    except APIConnectionError as e:  # includes APITimeoutError
        raise ProviderError(None, type(e).__name__) from e


class CartesiaProvider:
    """Shared by both modes; subclasses implement `_attempt`."""

    name = "cartesia"
    mode: Mode
    format = "wav"  # stored as WAV in both modes (stream wraps raw PCM)

    def __init__(self, config: ProviderConfig, api_key: str) -> None:
        from cartesia import Cartesia

        self.config = config
        self.codec, self.sample_rate = parse_output_format(config.output_format)
        # The SDK sends `Cartesia-Version` itself. Retries are ours (with_retries), so the SDK's are off.
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

    def _attempt(self, text: str) -> SynthesisResult:
        raise NotImplementedError

    def synthesize(self, text: str) -> SynthesisResult:
        result, attempts = with_retries(lambda: self._attempt(text))
        return SynthesisResult(**{**result.__dict__, "attempts": attempts})

    def close(self) -> None:
        self._client.close()
