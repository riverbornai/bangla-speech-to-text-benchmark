"""Gemini-TTS via google-genai: batch = `generate_content()`, stream = `generate_content_stream()`.

The text is sent as it is. The only exception is the emotive variant: its style tags (the entries of
config/gemini.json with tag_type "style") are cut out of the text and sent as `speech_metadata.style`.
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Collection, Iterator
from contextlib import contextmanager
from typing import Any

import httpx

from runner.config import ConfigError, ProviderConfig
from runner.dataset import DatasetItem
from runner.providers.base import Mode, ProviderError, SynthesisResult, collect_chunks, to_wav

TIMEOUT_MS = 120_000


# --- request: text -> parts --------------------------------------------------------------------------------


def build_parts(text: str, styles: Collection[str] = ()) -> list[dict[str, Any]]:
    """Turn the text into the request's parts.

    Baseline (no `styles`): one plain part holding the text unchanged.
    Emotive: the text is cut at every `[<style>]` marker and each piece becomes a part whose
    `speech_metadata.style` is the marker before it. A style lasts until the next marker, and text before
    the first marker has no style. Only exact style values count, so `[বিজ্ঞপ্তি]` stays text.
    """
    if not styles:
        return [{"text": text}]

    marker = re.compile(
        r"\[(" + "|".join(re.escape(s) for s in sorted(styles, key=len, reverse=True)) + r")\]"
    )
    pieces = marker.split(text)  # [text, style, text, style, text, ...]
    parts = []
    for style, piece in zip([None, *pieces[1::2]], pieces[0::2], strict=True):
        piece = piece.strip()
        if not piece:
            continue
        part: dict[str, Any] = {"text": piece}
        if style:
            part["speech_metadata"] = {"style": style}
        parts.append(part)
    return parts or [{"text": text}]  # only markers, nothing to style: send as is


# --- response: audio ---------------------------------------------------------------------------------------


def parse_output_format(output_format: str) -> tuple[str, int]:
    """'wav_24000' -> ('wav', 24000). Gemini returns 16-bit mono PCM; we always store it as WAV."""
    codec, _, rate = output_format.partition("_")
    if codec != "wav" or not rate.isdigit():
        raise ConfigError(f"gemini: unsupported output format {output_format!r} (only wav_<rate>)")
    return codec, int(rate)


def audio_parts(response: Any) -> Iterator[bytes]:
    """The audio bytes in one response; safety blocks and empty responses yield nothing."""
    for candidate in response.candidates or []:
        for part in candidate.content.parts if candidate.content and candidate.content.parts else []:
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


# --- provider ----------------------------------------------------------------------------------------------


class GeminiProvider:
    """Shared by both modes; the subclasses only differ in how they call the SDK."""

    name = "gemini"
    mode: Mode

    def __init__(self, config: ProviderConfig) -> None:
        from google import genai
        from google.genai import types

        if config.voice_settings:
            raise ConfigError("gemini: voice_settings are not supported (baseline uses the default style)")
        self.config = config
        self.format, self.sample_rate = parse_output_format(config.output_format)
        # Auth is ADC (the job's service account); the project falls back to the ADC project.
        self._client = genai.Client(
            enterprise=True,
            project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
            location=config.location or "global",
            http_options=types.HttpOptions(
                timeout=TIMEOUT_MS,
                retry_options=types.HttpRetryOptions(attempts=1),  # no retries
            ),
        )

    def supports(self, item: DatasetItem) -> bool:
        return self.config.max_chars is None or len(item.text) <= self.config.max_chars

    def _request(self, text: str) -> dict[str, Any]:
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
        self, audio: bytes, text: str, ttfb_ms: float | None, total_ms: float, request_id: str | None
    ) -> SynthesisResult:
        return SynthesisResult(
            audio=to_wav(audio, self.sample_rate),
            format=self.format,
            sample_rate=self.sample_rate,
            ttfb_ms=ttfb_ms,
            total_ms=total_ms,
            billed_chars=len(text),
            request_id=request_id,
        )

    def close(self) -> None:
        self._client.close()


class GeminiBatch(GeminiProvider):
    """`models.generate_content()`: the whole clip comes back in one response."""

    mode = "batch"

    def synthesize(self, text: str) -> SynthesisResult:
        start = time.perf_counter_ns()
        with sdk_errors():
            response = self._client.models.generate_content(**self._request(text))
        total_ms = (time.perf_counter_ns() - start) / 1e6

        audio = b"".join(audio_parts(response))
        if not audio:
            raise ProviderError(200, "empty_audio", response.response_id)
        return self._result(audio, text, None, total_ms, response.response_id)  # batch: no TTFB


class GeminiStream(GeminiProvider):
    """`models.generate_content_stream()`: audio arrives in chunks while the model renders."""

    mode = "stream"

    def synthesize(self, text: str) -> SynthesisResult:
        request_ids: list[str] = []

        def chunks() -> Iterator[bytes]:
            for response in self._client.models.generate_content_stream(**self._request(text)):
                if response.response_id:
                    request_ids.append(response.response_id)
                yield from audio_parts(response)

        start = time.perf_counter_ns()
        with sdk_errors():
            audio, ttfb_ms, total_ms = collect_chunks(start, chunks())
        return self._result(audio, text, ttfb_ms, total_ms, request_ids[0] if request_ids else None)


def create(config: ProviderConfig) -> GeminiProvider:
    cls = GeminiStream if config.mode == "stream" else GeminiBatch
    return cls(config)


__all__ = [
    "GeminiBatch",
    "GeminiProvider",
    "GeminiStream",
    "build_parts",
    "create",
    "parse_output_format",
    "to_wav",
]
