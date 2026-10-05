from __future__ import annotations

import time

from runner.providers.base import SynthesisResult, collect_chunks
from runner.providers.sarvam._common import SarvamProvider, sdk_errors


class SarvamStream(SarvamProvider):
    """`text_to_speech.convert_stream()` -> POST /text-to-speech/stream: raw audio bytes as they render."""

    mode = "stream"

    def _attempt(self, text: str) -> SynthesisResult:
        start = time.perf_counter_ns()
        with sdk_errors():
            audio, ttfb_ms, total_ms = collect_chunks(
                start, self._client.text_to_speech.convert_stream(**self._params(text))
            )
        return SynthesisResult(
            audio=audio,
            format=self.format,
            sample_rate=self.sample_rate,
            ttfb_ms=ttfb_ms,
            total_ms=total_ms,
            billed_chars=len(text),
            request_id=None,  # the stream iterator doesn't expose response headers
            attempts=1,
        )
