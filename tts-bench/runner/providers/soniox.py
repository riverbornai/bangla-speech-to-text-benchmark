"""Soniox: batch = `tts.generate()` (REST), stream = `realtime.tts.connect()` (WebSocket)."""

from __future__ import annotations

import os
import re
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import httpx

from runner.config import ConfigError, ProviderConfig
from runner.dataset import DatasetItem
from runner.providers.base import (
    Mode,
    ProviderError,
    SynthesisResult,
    collect_chunks,
    to_wav,
)

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
        # import pdb
        # pdb.set_trace()
        code = e.api_error.error_type if e.api_error else f"http_{e.status_code}"
        raise ProviderError(
            e.status_code,
            str(code)[:100],
            e.request_id,
        ) from e
    except SonioxRealtimeError as e:
        # Server errors end in "(code N)" with an HTTP-like N; timeouts and disconnects carry no code and
        # are treated as transport failures. The message text itself is not kept.
        match = _REALTIME_CODE.search(str(e))
        raise ProviderError(int(match.group(1)) if match else None, "realtime_error") from e
    except httpx.TransportError as e:
        raise ProviderError(None, type(e).__name__) from e


class SonioxProvider:
    """Shared by both modes; subclasses implement `synthesize`."""

    name = "soniox"
    mode: Mode
    format = "wav"  # stored file type; streamed PCM is wrapped in a WAV header

    def __init__(self, config: ProviderConfig, api_key: str) -> None:
        from soniox import SonioxClient

        if not config.language_code:
            raise ConfigError("soniox: language_code is required (e.g. bn)")
        self.config = config
        self.codec, self.sample_rate = parse_output_format(config.output_format)
        self._client = SonioxClient(
            api_key=api_key,
            timeout_sec=TIMEOUT_SEC,
            tts_api_base_url="https://tts-rt.eu.soniox.com",  # EU region: REST and WebSocket must match
            tts_websocket_base_url="wss://tts-rt.eu.soniox.com/tts-websocket",
        )

    def supports(self, item: DatasetItem) -> bool:
        return self.config.max_chars is None or len(item.text) <= self.config.max_chars

    def _result(self, audio: bytes, text: str, ttfb_ms: float | None, total_ms: float) -> SynthesisResult:
        return SynthesisResult(
            audio=to_wav(audio, self.sample_rate),  # Soniox's WAV header has a placeholder data length
            format=self.format,
            sample_rate=self.sample_rate,
            ttfb_ms=ttfb_ms,
            total_ms=total_ms,
            billed_chars=len(text),
            request_id=None,  # success responses carry no id (the SDK returns plain bytes / audio events)
        )

    def close(self) -> None:
        self._client.close()


class SonioxBatch(SonioxProvider):
    """`tts.generate()` -> POST https://tts-rt.eu.soniox.com/tts: the clip is rendered, then sent whole."""

    mode = "batch"

    def synthesize(self, text: str) -> SynthesisResult:
        from soniox.types import CreateTtsConfig

        config = CreateTtsConfig(audio_format=AUDIO_FORMATS[self.codec], sample_rate=self.sample_rate)
        start = time.perf_counter_ns()
        with sdk_errors():
            audio = self._client.tts.generate(
                text=text,
                voice=self.config.voice.id,
                model=self.config.model,
                language=self.config.language_code,
                config=config,
            )
        total_ms = (time.perf_counter_ns() - start) / 1e6
        if not audio:
            raise ProviderError(200, "empty_audio")
        return self._result(audio, text, None, total_ms)  # batch: no TTFB


class SonioxStream(SonioxProvider):
    """Realtime TTS over a WebSocket: audio events arrive while the model renders.

    One connection per item. The clock starts right before the text is sent, after the socket is open:
    that is the moment the request is made, and it excludes the WebSocket handshake that the HTTP providers
    (pooled connections) do not pay per request. TTFB is the first non-empty audio chunk.
    """

    mode = "stream"

    def __init__(self, config: ProviderConfig, api_key: str) -> None:
        super().__init__(config, api_key)
        if self.codec != "pcm":
            # A streamed WAV header is unverified; stream raw PCM and wrap it ourselves.
            raise ConfigError(
                f"soniox: stream mode needs a pcm_<rate> output_format, got {config.output_format!r}"
            )

    def synthesize(self, text: str) -> SynthesisResult:
        from soniox.types import RealtimeTTSConfig

        config = RealtimeTTSConfig(
            stream_id=uuid.uuid4().hex,
            model=self.config.model,
            language=self.config.language_code,
            voice=self.config.voice.id,
            audio_format=AUDIO_FORMATS[self.codec],
            sample_rate=self.sample_rate,
        )
        with sdk_errors(), self._client.realtime.tts.connect(config=config) as session:
            start = time.perf_counter_ns()
            session.send_text_chunk(text, text_end=True)  # whole text in one message, then no more
            audio, ttfb_ms, total_ms = collect_chunks(start, session.receive_audio_chunks())
        return self._result(audio, text, ttfb_ms, total_ms)


__all__ = ["SonioxBatch", "SonioxProvider", "SonioxStream", "create", "parse_output_format"]


def create(config: ProviderConfig) -> SonioxProvider:
    api_key = os.environ.get("SONIOX_API_KEY")
    if not api_key:
        raise ConfigError("SONIOX_API_KEY is not set (expected in .env)")
    cls = SonioxStream if config.mode == "stream" else SonioxBatch
    return cls(config, api_key)
