from __future__ import annotations

import time

from runner.providers.base import ProviderError, SynthesisResult
from runner.providers.openai_tts._common import REQUEST_ID_HEADER, OpenAITTSProvider, sdk_errors


class OpenAIBatch(OpenAITTSProvider):
    """`audio.speech.create()` -> POST /v1/audio/speech: the whole clip is returned in one response."""

    mode = "batch"

    def _attempt(self, text: str) -> SynthesisResult:
        start = time.perf_counter_ns()
        with sdk_errors():
            # The raw response exposes the headers (request id); `.parse()` gives the binary body.
            raw = self._client.audio.speech.with_raw_response.create(**self._params(text))
            audio = raw.parse().content
        total_ms = (time.perf_counter_ns() - start) / 1e6

        request_id = raw.headers.get(REQUEST_ID_HEADER)
        if not audio:
            raise ProviderError(200, "empty_audio", request_id)
        return self._result(audio, text, None, total_ms, request_id)  # batch: no TTFB
