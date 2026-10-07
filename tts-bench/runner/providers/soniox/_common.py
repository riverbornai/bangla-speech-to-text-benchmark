from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager

import httpx

from runner.config import ConfigError, ProviderConfig
from runner.dataset import DatasetItem
from runner.providers.base import Mode, ProviderError, SynthesisResult, pcm_to_wav, with_retries

TIMEOUT_SEC = 120.0
SAMPLE_RATES = (8000, 16000, 24000, 44100, 48000)
# Soniox audio_format names for the config's short codec names.
AUDIO_FORMATS = {"wav": "wav", "pcm": "pcm_s16le"}
_REALTIME_CODE = re.compile(r"\(code (\d+)\)\s*$")  # SDK: "<server message> (code <error_code>)"


def parse_output_format(output_format: str) -> tuple[str, int]:
    """'wav_24000' -> ('wav', 24000); 'pcm_24000' -> ('pcm', 24000)."""
    codec, _, rate = output_format.partition("_")
    if codec not in AUDIO_FORMATS or not rate.isdigit() or int(rate) not in SAMPLE_RATES:
        raise ConfigError(f"soniox: unsupported output format {output_format!r} (wav_<rate> or pcm_<rate>)")
    return codec, int(rate)


@contextmanager
def sdk_errors() -> Iterator[None]:
    from soniox.errors import SonioxAPIError, SonioxRealtimeError

    try:
        yield
    except SonioxAPIError as e:
        # Only the short error_type (e.g. limit_exceeded), never the message body.
        # A non-JSON body has no api_error.
        code = e.api_error.error_type if e.api_error else f"http_{e.status_code}"
        retry_after = e.response.headers.get("retry-after") if e.response is not None else None
        raise ProviderError(
            e.status_code,
            str(code)[:100],
            e.request_id,
            float(retry_after) if retry_after and retry_after.isdigit() else None,
        ) from e
    except SonioxRealtimeError as e:
        # Server errors end in "(code N)" with an HTTP-like N; timeouts and disconnects carry no code and
        # are treated as transport failures (retryable). The message text itself is not kept.
        match = _REALTIME_CODE.search(str(e))
        raise ProviderError(int(match.group(1)) if match else None, "realtime_error") from e
    except httpx.TransportError as e:
        raise ProviderError(None, type(e).__name__) from e


class SonioxProvider:
    """Shared by both modes; subclasses implement `_attempt`."""

    name = "soniox"
    mode: Mode
    format = "wav"  # stored file type; streamed PCM is wrapped in a WAV header

    def __init__(self, config: ProviderConfig, api_key: str) -> None:
        from soniox import SonioxClient

        if not config.language_code:
            raise ConfigError("soniox: language_code is required (e.g. bn)")
        self.config = config
        self.codec, self.sample_rate = parse_output_format(config.output_format)
        self._client = SonioxClient(api_key=api_key, timeout_sec=TIMEOUT_SEC)  # the SDK does not retry

    def supports(self, item: DatasetItem) -> bool:
        return self.config.max_chars is None or len(item.text) <= self.config.max_chars

    def _result(self, audio: bytes, text: str, ttfb_ms: float | None, total_ms: float) -> SynthesisResult:
        if self.codec == "pcm":
            audio = pcm_to_wav(audio, self.sample_rate)
        return SynthesisResult(
            audio=audio,
            format=self.format,
            sample_rate=self.sample_rate,
            ttfb_ms=ttfb_ms,
            total_ms=total_ms,
            billed_chars=len(text),
            request_id=None,  # success responses carry no id (the SDK returns plain bytes / audio events)
            attempts=1,
        )

    def _attempt(self, text: str) -> SynthesisResult:
        raise NotImplementedError

    def synthesize(self, text: str) -> SynthesisResult:
        result, attempts = with_retries(lambda: self._attempt(text))
        return SynthesisResult(**{**result.__dict__, "attempts": attempts})

    def close(self) -> None:
        self._client.close()
