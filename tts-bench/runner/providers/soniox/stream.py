from __future__ import annotations

import time
import uuid

from runner.config import ConfigError, ProviderConfig
from runner.providers.base import SynthesisResult, collect_chunks
from runner.providers.soniox._common import AUDIO_FORMATS, SonioxProvider, sdk_errors


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

    def _attempt(self, text: str) -> SynthesisResult:
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
