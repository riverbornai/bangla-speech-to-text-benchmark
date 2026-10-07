from __future__ import annotations

import io
import os
import wave
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from typing import Any

import httpx

from runner.config import ConfigError, ProviderConfig
from runner.dataset import DatasetItem
from runner.providers.base import Mode, ProviderError, SynthesisResult, with_retries
from runner.providers.gemini.styles import build_parts

TIMEOUT_MS = 120_000


def parse_output_format(output_format: str) -> tuple[str, int]:
    """'wav_24000' -> ('wav', 24000). Gemini returns 16-bit mono PCM; we always store it as WAV."""
    codec, _, rate = output_format.partition("_")
    if codec != "wav" or not rate.isdigit():
        raise ConfigError(f"gemini: unsupported output format {output_format!r} (only wav_<rate>)")
    return codec, int(rate)


def to_wav(audio: bytes, sample_rate: int) -> bytes:
    """Normalise the model output (RIFF WAV, or headerless L16 PCM) to a WAV with a correct header.

    Streaming chunks are concatenated, so a streamed RIFF header can carry a placeholder length.
    """
    if audio[:4] == b"RIFF":
        at = audio.find(b"data")
        if at < 0:
            raise ProviderError(200, "bad_wav")
        audio = audio[at + 8 :]
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(audio)
    return buf.getvalue()


def audio_parts(response: Any) -> Iterator[bytes]:
    for cand in response.candidates or []:
        for part in cand.content.parts if cand.content and cand.content.parts else []:
            if part.inline_data and part.inline_data.data:
                yield part.inline_data.data


@contextmanager
def sdk_errors() -> Iterator[None]:
    from google.genai import errors

    try:
        yield
    except errors.APIError as e:
        # Only the short status string; never the full body.
        raise ProviderError(e.code, str(e.status or f"http_{e.code}")[:100]) from e
    except httpx.TransportError as e:
        raise ProviderError(None, type(e).__name__) from e


class GeminiProvider:
    """Shared by both modes; subclasses implement `_attempt`."""

    name = "gemini"
    mode: Mode

    def __init__(self, config: ProviderConfig) -> None:
        from google import genai
        from google.genai import types

        self.config = config
        self.format, self.sample_rate = parse_output_format(config.output_format)
        if config.voice_settings:
            raise ConfigError("gemini: voice_settings are not supported (baseline uses the default style)")
        # Auth is ADC (the job's service account); the project falls back to the ADC project.
        self._client = genai.Client(
            enterprise=True,
            project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
            location=config.location or "global",
            http_options=types.HttpOptions(
                timeout=TIMEOUT_MS,
                retry_options=types.HttpRetryOptions(attempts=1),  # retries handled by with_retries
            ),
        )

    def supports(self, item: DatasetItem) -> bool:
        return self.config.max_chars is None or len(item.text) <= self.config.max_chars

    def _request(self, text: str) -> dict[str, Any]:
        # Leading `[style]` tags in the dataset text become `speech_metadata`; untagged text is sent as-is.
        return {
            "model": self.config.model,
            "contents": [{"role": "user", "parts": build_parts(text, self.config.emotive_styles)}],
            "config": {
                "response_modalities": ["AUDIO"],
                "speech_config": {
                    "language_code": self.config.language_code,
                    "voice_config": {"voice": self.config.voice.id},
                },
            },
        }

    def _result(
        self,
        chunks: Iterable[bytes],
        text: str,
        ttfb_ms: float | None,
        total_ms: float,
        request_id: str | None,
    ) -> SynthesisResult:
        return SynthesisResult(
            audio=to_wav(b"".join(chunks), self.sample_rate),
            format=self.format,
            sample_rate=self.sample_rate,
            ttfb_ms=ttfb_ms,
            total_ms=total_ms,
            billed_chars=len(text),
            request_id=request_id,
            attempts=1,
        )

    def _attempt(self, text: str) -> SynthesisResult:
        raise NotImplementedError

    def synthesize(self, text: str) -> SynthesisResult:
        result, attempts = with_retries(lambda: self._attempt(text))
        return SynthesisResult(**{**result.__dict__, "attempts": attempts})

    def close(self) -> None:
        self._client.close()
