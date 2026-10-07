from __future__ import annotations

import time

from runner.providers.base import SynthesisResult, collect_chunks
from runner.providers.gemini._common import GeminiProvider, audio_parts, sdk_errors


class GeminiStream(GeminiProvider):
    """`models.generate_content_stream()`: audio arrives in chunks while the model renders."""

    mode = "stream"

    def _attempt(self, text: str) -> SynthesisResult:
        request_ids: list[str] = []

        def chunks():
            for resp in self._client.models.generate_content_stream(**self._request(text)):
                if resp.response_id:
                    request_ids.append(resp.response_id)
                yield from audio_parts(resp)

        start = time.perf_counter_ns()
        with sdk_errors():
            audio, ttfb_ms, total_ms = collect_chunks(start, chunks())
        return self._result([audio], text, ttfb_ms, total_ms, request_ids[0] if request_ids else None)
