from __future__ import annotations

import io
import shutil
import subprocess
import wave

import pytest

from runner.main import audio_seconds


def _wav(seconds: float, rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    return buf.getvalue()


def test_pcm_and_wav() -> None:
    assert audio_seconds(b"\x00\x00" * 24000, "pcm", 24000) == 1.0
    assert audio_seconds(_wav(0.5), "wav", 24000) == 0.5


def test_unreadable_audio_is_none() -> None:
    assert audio_seconds(b"", "pcm", 24000) is None
    assert audio_seconds(b"not audio", "mp3", 44100) is None


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg/ffprobe (present in the image)")
def test_mp3_duration_via_ffprobe() -> None:
    mp3 = subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "s16le", "-ar", "44100", "-ac", "1", "-i", "pipe:0",
         "-c:a", "libmp3lame", "-b:a", "128k", "-f", "mp3", "pipe:1"],
        input=b"\x00\x00" * 44100 * 2, capture_output=True, check=True,
    ).stdout  # fmt: skip
    assert audio_seconds(mp3, "mp3", 44100) == pytest.approx(2.0, abs=0.06)
