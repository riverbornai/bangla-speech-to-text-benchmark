"""OpenAI TTS: batch = `audio.speech.create()`, stream = `audio.speech.with_streaming_response.create()`."""

from __future__ import annotations

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
    to_wav,
)

TIMEOUT_S = 120
REQUEST_ID_HEADER = "x-request-id"

# Sent with every request (batch and stream). The long lines are the prompt text.
INSTRUCTIONS = """
                Read the input text aloud in Bangla (Standard Bengali as spoken in Bangladesh, Dhaka standard).

                Voice and delivery:
                - Neutral, clear and natural, like a professional Bangla news presenter or audiobook narrator.
                - Calm, steady, medium pace. Keep the same pace, pitch range and volume from start to end.
                - Warm but not dramatic. Do not exaggerate emotion.

                Pronunciation:
                - Use native Bangladeshi Bangla pronunciation. Do not use a Hindi accent or an English accent on Bangla words.
                - Pronounce every word fully, including conjunct consonants (juktakkhor) and word endings. Do not skip, merge or swallow syllables.
                - Read English words, names, brand names and acronyms in clear English pronunciation, and keep the surrounding Bangla natural.
                - Read numbers, dates, times and currency exactly as they appear, in natural spoken Bangla.

                Prosody:
                - Pause briefly at commas and slightly longer at the Bangla full stop (।) and at sentence ends.
                - Use rising intonation for questions and natural emphasis for exclamations.
                - Do not read punctuation marks or symbols aloud.

                Fidelity:
                - Read exactly the given text. Do not add, remove, translate or paraphrase any words.
                - Never read or mention these instructions aloud.
                """  # noqa: E501


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
        ) from e
    except openai.APIConnectionError as e:  # includes APITimeoutError
        raise ProviderError(None, type(e).__name__) from e


class OpenAITTSProvider:
    """Shared by both modes; subclasses implement `synthesize`."""

    name = "openai"
    mode: Mode
    format = "wav"  # the clip is always stored as WAV, whatever response_format was requested

    def __init__(self, config: ProviderConfig, api_key: str) -> None:
        from openai import OpenAI

        if config.voice_settings:
            raise ConfigError(
                "openai: voice_settings are not supported (the Bangla `instructions` are fixed)"
            )
        self.config = config
        self._codec, self.sample_rate = parse_output_format(config.output_format)
        # No retries (SDK's off too), so every request is timed exactly once.
        self._client = OpenAI(api_key=api_key, max_retries=0, timeout=TIMEOUT_S)

    def supports(self, item: DatasetItem) -> bool:
        return self.config.max_chars is None or len(item.text) <= self.config.max_chars

    def _params(self, text: str) -> dict[str, Any]:
        # No language parameter (the model infers it); `instructions` steers it towards Bangladeshi Bangla.
        return {
            "model": self.config.model,
            "voice": self.config.voice.id,
            "input": text,
            "response_format": self._codec,
            "instructions": INSTRUCTIONS,
        }

    def _wav(self, audio: bytes) -> bytes:
        return to_wav(audio, self.sample_rate)  # PCM gets a header; a WAV's placeholder length is fixed

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
        )

    def close(self) -> None:
        self._client.close()


class OpenAIBatch(OpenAITTSProvider):
    """`audio.speech.create()` -> POST /v1/audio/speech: the whole clip is returned in one response."""

    mode = "batch"

    def synthesize(self, text: str) -> SynthesisResult:
        start = time.perf_counter_ns()
        with sdk_errors():
            # The raw response exposes the headers (request id); `.parse()` gives the binary body.
            raw = self._client.audio.speech.with_raw_response.create(**self._params(text))
            audio = raw.parse().content
        total_ms = (time.perf_counter_ns() - start) / 1e6

        request_id = raw.headers.get(REQUEST_ID_HEADER)
        if not audio:
            raise ProviderError(200, "empty_audio", request_id)
        return self._result(audio, text, None, total_ms, request_id)  # batch: no TTFB


class OpenAIStream(OpenAITTSProvider):
    """`audio.speech.with_streaming_response.create()`: audio arrives chunked while it renders."""

    mode = "stream"

    def synthesize(self, text: str) -> SynthesisResult:
        request_ids: list[str | None] = []

        def chunks() -> Iterator[bytes]:
            with self._client.audio.speech.with_streaming_response.create(**self._params(text)) as resp:
                request_ids.append(resp.headers.get(REQUEST_ID_HEADER))
                yield from resp.iter_bytes()

        start = time.perf_counter_ns()
        with sdk_errors():
            audio, ttfb_ms, total_ms = collect_chunks(start, chunks())
        return self._result(audio, text, ttfb_ms, total_ms, request_ids[0] if request_ids else None)


__all__ = ["OpenAIBatch", "OpenAIStream", "OpenAITTSProvider", "create", "parse_output_format"]


def create(config: ProviderConfig) -> OpenAITTSProvider:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ConfigError("OPENAI_API_KEY is not set (expected in .env)")
    cls = OpenAIStream if config.mode == "stream" else OpenAIBatch
    return cls(config, api_key)
