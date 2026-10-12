"""Azure AI Speech (Neural TTS) over the REST API: one SSML request per item.

Batch reads the whole response; stream reads the same response chunk by chunk to time the first byte.
The REST API is used (as in the original batch_tts.py / tts.py) instead of the
`azure-cognitiveservices-speech` SDK: it is one plain HTTPS call and the image needs no native wheel.
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from xml.sax.saxutils import escape

import httpx

from runner.config import ConfigError, ProviderConfig
from runner.dataset import DatasetItem
from runner.providers.base import Mode, ProviderError, SynthesisResult, collect_chunks, to_wav

TIMEOUT_S = 120.0
USER_AGENT = "bangla-tts-benchmark"
REQUEST_ID_HEADER = "x-requestid"  # not documented by Azure: check a real response
# config output_format -> the X-Microsoft-OutputFormat header value
OUTPUT_FORMATS = {
    "wav_24000": "riff-24khz-16bit-mono-pcm",
    "wav_48000": "riff-48khz-16bit-mono-pcm",
}
# Short, fixed error codes: the response body is never kept.
STATUS_CODES = {400: "bad_request", 401: "unauthorized", 403: "forbidden", 429: "too_many_requests"}
# The only markup passed through unescaped: a pause such as <break time="700ms"/> (config/azure.json).
_BREAK = re.compile(r'(<break time="\d+(?:\.\d+)?(?:ms|s)"/>)')


def parse_output_format(output_format: str) -> tuple[str, int]:
    """'wav_24000' -> ('wav', 24000)."""
    if output_format not in OUTPUT_FORMATS:
        raise ConfigError(
            f"azure: unsupported output format {output_format!r} (have {sorted(OUTPUT_FORMATS)})"
        )
    codec, _, rate = output_format.partition("_")
    return codec, int(rate)


def to_ssml(text: str, voice: str, language: str) -> str:
    """Wrap the text in SSML. The text is XML-escaped (`&`, `<`, `>` are valid dataset characters), except
    for `<break .../>` pauses, which the emotive variant maps from the pause tags."""
    body = "".join(part if _BREAK.fullmatch(part) else escape(part) for part in _BREAK.split(text))
    return (
        '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
        f'xml:lang="{language}"><voice name="{voice}">{body}</voice></speak>'
    )


@contextmanager
def sdk_errors() -> Iterator[None]:
    try:
        yield
    except httpx.TransportError as e:
        raise ProviderError(None, type(e).__name__) from e


class AzureProvider:
    """Shared by both modes; the subclasses only differ in how they read the response."""

    name = "azure"
    mode: Mode
    format = "wav"

    def __init__(self, config: ProviderConfig, api_key: str, region: str) -> None:
        if not config.language_code:
            raise ConfigError("azure: language_code is required (e.g. bn-BD)")
        self.config = config
        self.codec, self.sample_rate = parse_output_format(config.output_format)
        self._url = f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"
        self._headers = {
            "Ocp-Apim-Subscription-Key": api_key,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": OUTPUT_FORMATS[config.output_format],
            "User-Agent": USER_AGENT,
        }
        self._client = httpx.Client(timeout=TIMEOUT_S)  # no retries: every request is timed once

    def supports(self, item: DatasetItem) -> bool:
        return self.config.max_chars is None or len(item.text) <= self.config.max_chars

    def _body(self, text: str) -> bytes:
        return to_ssml(text, self.config.voice.id, self.config.language_code or "").encode("utf-8")

    def _check(self, response: httpx.Response) -> None:
        if response.status_code != 200:
            raise ProviderError(
                response.status_code,
                STATUS_CODES.get(response.status_code, f"http_{response.status_code}"),
                response.headers.get(REQUEST_ID_HEADER),
            )

    def _result(
        self, audio: bytes, text: str, ttfb_ms: float | None, total_ms: float, request_id: str | None
    ):
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


class AzureBatch(AzureProvider):
    """POST the SSML and read the whole response."""

    mode = "batch"

    def synthesize(self, text: str) -> SynthesisResult:
        start = time.perf_counter_ns()
        with sdk_errors():
            response = self._client.post(self._url, headers=self._headers, content=self._body(text))
        total_ms = (time.perf_counter_ns() - start) / 1e6

        self._check(response)
        if not response.content:
            raise ProviderError(200, "empty_audio", response.headers.get(REQUEST_ID_HEADER))
        return self._result(response.content, text, None, total_ms, response.headers.get(REQUEST_ID_HEADER))


class AzureStream(AzureProvider):
    """POST the SSML and read the response as it arrives: TTFB is the first non-empty chunk."""

    mode = "stream"

    def synthesize(self, text: str) -> SynthesisResult:
        start = time.perf_counter_ns()
        with (
            sdk_errors(),
            self._client.stream(
                "POST", self._url, headers=self._headers, content=self._body(text)
            ) as response,
        ):
            self._check(response)
            audio, ttfb_ms, total_ms = collect_chunks(start, response.iter_bytes())
            request_id = response.headers.get(REQUEST_ID_HEADER)
        return self._result(audio, text, ttfb_ms, total_ms, request_id)


def create(config: ProviderConfig) -> AzureProvider:
    key, region = os.environ.get("AZURE_SPEECH_KEY"), os.environ.get("AZURE_SPEECH_REGION")
    if not key or not region:
        raise ConfigError("AZURE_SPEECH_KEY and AZURE_SPEECH_REGION must both be set (expected in .env)")
    cls = AzureStream if config.mode == "stream" else AzureBatch
    return cls(config, key, region)


__all__ = ["AzureBatch", "AzureProvider", "AzureStream", "create", "parse_output_format", "to_ssml"]
