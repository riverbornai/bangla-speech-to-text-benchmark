from __future__ import annotations

import base64
import time
from collections.abc import Iterator

from runner.providers.base import ProviderError, SynthesisResult, collect_chunks, pcm_to_wav
from runner.providers.cartesia._common import CartesiaProvider, sdk_errors


class CartesiaStream(CartesiaProvider):
    """`tts.generate_sse()` -> POST /tts/sse: base64 PCM chunks while the model renders.

    SSE documents only raw encodings, so this asks for `raw` pcm_s16le and wraps it as WAV at the end.
    """

    mode = "stream"

    def _chunks(self, text: str) -> Iterator[bytes]:
        for event in self._client.tts.generate_sse(**self._params(text, "raw")):
            if event.type == "chunk":
                yield base64.b64decode(event.data or "")
            elif event.type == "error":
                # In-band error: keep only the short code, never the message.
                raise ProviderError(
                    event.status_code,
                    str(event.error_code or f"http_{event.status_code}")[:100],
                    event.request_id,
                )

    def _attempt(self, text: str) -> SynthesisResult:
        start = time.perf_counter_ns()
        with sdk_errors():
            pcm, ttfb_ms, total_ms = collect_chunks(start, self._chunks(text))
        return SynthesisResult(
            audio=pcm_to_wav(pcm, self.sample_rate),
            format=self.format,
            sample_rate=self.sample_rate,
            ttfb_ms=ttfb_ms,
            total_ms=total_ms,
            billed_chars=len(text),
            request_id=None,  # chunk events carry a context_id, not a request id
            attempts=1,
        )
