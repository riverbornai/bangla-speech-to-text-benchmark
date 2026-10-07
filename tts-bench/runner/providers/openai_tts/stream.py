from __future__ import annotations

import time
from collections.abc import Iterator

from runner.providers.base import SynthesisResult, collect_chunks
from runner.providers.openai_tts._common import REQUEST_ID_HEADER, OpenAITTSProvider, sdk_errors


class OpenAIStream(OpenAITTSProvider):
    """`audio.speech.with_streaming_response.create()`: audio arrives chunked while it renders."""

    mode = "stream"

    def _attempt(self, text: str) -> SynthesisResult:
        request_ids: list[str | None] = []

        def chunks() -> Iterator[bytes]:
            with self._client.audio.speech.with_streaming_response.create(**self._params(text)) as resp:
                request_ids.append(resp.headers.get(REQUEST_ID_HEADER))
                yield from resp.iter_bytes()

        start = time.perf_counter_ns()
        with sdk_errors():
            audio, ttfb_ms, total_ms = collect_chunks(start, chunks())
        return self._result(audio, text, ttfb_ms, total_ms, request_ids[0] if request_ids else None)
