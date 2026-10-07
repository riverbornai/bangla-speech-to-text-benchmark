from __future__ import annotations

import io
import random
import time
import wave
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Literal, Protocol

from runner.dataset import DatasetItem

MAX_ATTEMPTS = 5
sleep = time.sleep

Mode = Literal["batch", "stream"]
MODES: tuple[Mode, ...] = ("batch", "stream")


@dataclass(frozen=True)
class SynthesisResult:
    audio: bytes
    format: str  # "wav" | "mp3" | "pcm" | "ogg"
    sample_rate: int
    ttfb_ms: float | None  # request sent -> first audio byte; None in batch mode (it would equal total_ms)
    total_ms: float  # request sent -> last audio byte received
    billed_chars: int
    request_id: str | None
    attempts: int


class TTSProvider(Protocol):
    name: str
    mode: Mode
    format: str  # file extension of the native output, needed before synthesis for resume checks

    def supports(self, item: DatasetItem) -> bool: ...

    def synthesize(self, text: str) -> SynthesisResult: ...

    def close(self) -> None: ...


class ProviderError(Exception):
    """status=None means a transport failure (timeout, connection reset)."""

    def __init__(
        self,
        status: int | None,
        message: str,
        request_id: str | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.request_id = request_id
        self.retry_after = retry_after
        self.attempts = 1

    @property
    def retryable(self) -> bool:
        return self.status is None or self.status == 429 or self.status >= 500


def with_retries[T](fn: Callable[[], T]) -> tuple[T, int]:
    """Exponential backoff with jitter on 429/5xx/transport errors only."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return fn(), attempt
        except ProviderError as e:
            e.attempts = attempt
            if not e.retryable or attempt == MAX_ATTEMPTS:
                raise
            sleep(max(e.retry_after or 0.0, random.uniform(0, min(30.0, 2 ** (attempt - 1)))))
    raise AssertionError("unreachable")


def collect_chunks(start_ns: int, chunks: Iterable[bytes]) -> tuple[bytes, float, float]:
    """Join audio chunks -> (audio, ttfb_ms, total_ms); TTFB is the first non-empty chunk."""
    first_ns: int | None = None
    parts: list[bytes] = []
    for chunk in chunks:  # SDK errors surface while iterating, so call this inside the error mapping
        if chunk:
            first_ns = first_ns or time.perf_counter_ns()
            parts.append(chunk)
    end_ns = time.perf_counter_ns()
    if first_ns is None:
        raise ProviderError(200, "empty_audio")
    return b"".join(parts), (first_ns - start_ns) / 1e6, (end_ns - start_ns) / 1e6


def pcm_to_wav(pcm: bytes, sample_rate: int) -> bytes:
    """Wrap raw 16-bit mono little-endian PCM in a WAV header (for streams that only emit raw PCM)."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()
