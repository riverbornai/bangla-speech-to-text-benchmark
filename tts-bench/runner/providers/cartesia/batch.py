from __future__ import annotations

import time

from runner.providers.base import ProviderError, SynthesisResult
from runner.providers.cartesia._common import CartesiaProvider, sdk_errors


class CartesiaBatch(CartesiaProvider):
    """`tts.generate()` -> POST /tts/bytes: the clip is rendered, then sent as a WAV."""

    mode = "batch"

    def _attempt(self, text: str) -> SynthesisResult:
        start = time.perf_counter_ns()
        with sdk_errors():
            audio = self._client.tts.generate(**self._params(text, "wav")).read()
        total_ms = (time.perf_counter_ns() - start) / 1e6
        if not audio:
            raise ProviderError(200, "empty_audio")
        return SynthesisResult(
            audio=audio,
            format=self.format,
            sample_rate=self.sample_rate,
            ttfb_ms=None,  # batch: the whole clip arrives in one body
            total_ms=total_ms,
            billed_chars=len(text),
            request_id=None,  # no request-id response header is documented for successes
            attempts=1,
        )
