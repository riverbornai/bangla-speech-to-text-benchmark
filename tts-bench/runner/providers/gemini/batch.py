from __future__ import annotations

import time

from runner.providers.base import ProviderError, SynthesisResult
from runner.providers.gemini._common import GeminiProvider, audio_parts, sdk_errors


class GeminiBatch(GeminiProvider):
    """`models.generate_content()`: the whole clip returns in one response."""

    mode = "batch"

    def _attempt(self, text: str) -> SynthesisResult:
        start = time.perf_counter_ns()
        with sdk_errors():
            resp = self._client.models.generate_content(**self._request(text))
        total_ms = (time.perf_counter_ns() - start) / 1e6

        chunks = list(audio_parts(resp))
        if not chunks:
            raise ProviderError(200, "empty_audio", resp.response_id)
        return self._result(chunks, text, None, total_ms, resp.response_id)  # batch: no TTFB
