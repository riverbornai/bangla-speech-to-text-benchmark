from __future__ import annotations

import io
import time
import wave
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal, Protocol

from runner.dataset import DatasetItem

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


class TTSProvider(Protocol):
    name: str
    mode: Mode
    format: str  # file extension of the native output, needed before synthesis for resume checks

    def supports(self, item: DatasetItem) -> bool: ...

    def synthesize(self, text: str) -> SynthesisResult: ...

    def close(self) -> None: ...


class ProviderError(Exception):
    """A failed request. status=None means a transport failure (timeout, connection reset)."""

    def __init__(self, status: int | None, message: str, request_id: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.request_id = request_id


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


def _trailing_chunk(audio: bytes, start: int) -> int:
    """Index where trailing RIFF metadata begins, or len(audio). Gemini appends a C2PA (content credentials)
    chunk after the audio; it is a chunk header (id + size) whose size runs exactly to the end of the file."""
    at = audio.find(b"C2PA", start)
    while at >= 0:
        size = int.from_bytes(audio[at + 4 : at + 8], "little")
        if at + 8 + size + (size & 1) == len(audio):
            return at
        at = audio.find(b"C2PA", at + 1)
    return len(audio)


def to_wav(audio: bytes, sample_rate: int) -> bytes:
    """Re-wrap a provider's audio (a WAV/RIFF file or headerless 16-bit PCM) with a correct WAV header.

    Streamed chunks are concatenated, so a streamed header can carry a placeholder or per-chunk length and
    is not trusted: the audio runs to the end of the response, minus any trailing metadata chunk. Without
    that cut, Gemini's C2PA chunk would play as a burst of static at the end of the clip.
    """
    if audio[:4] == b"RIFF":
        at = audio.find(b"data")
        if at < 0:
            raise ProviderError(200, "bad_wav")
        start = at + 8  # skip the "data" tag and its 4-byte length
        audio = audio[start : _trailing_chunk(audio, start)]
    return pcm_to_wav(audio[: len(audio) - len(audio) % 2], sample_rate)
