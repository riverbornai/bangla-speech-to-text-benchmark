from __future__ import annotations

import base64
import binascii
import time

from runner.providers.base import ProviderError, SynthesisResult
from runner.providers.sarvam._common import SarvamProvider, sdk_errors


class SarvamBatch(SarvamProvider):
    """`text_to_speech.convert()` -> POST /text-to-speech: one JSON body with base64 audio."""

    mode = "batch"

    def _attempt(self, text: str) -> SynthesisResult:
        start = time.perf_counter_ns()
        with sdk_errors():
            resp = self._client.text_to_speech.convert(**self._params(text))
        total_ms = (time.perf_counter_ns() - start) / 1e6

        audios = resp.audios or []
        if len(audios) != 1:
            raise ProviderError(200, f"expected 1 audio, got {len(audios)}", resp.request_id)
        try:
            audio = base64.b64decode(audios[0], validate=True)
        except binascii.Error as e:
            raise ProviderError(200, "bad_base64", resp.request_id) from e
        if not audio:
            raise ProviderError(200, "empty_audio", resp.request_id)
        return SynthesisResult(
            audio=audio,
            format=self.format,
            sample_rate=self.sample_rate,
            ttfb_ms=None,  # batch: the whole clip arrives in one JSON body
            total_ms=total_ms,
            billed_chars=len(text),
            request_id=resp.request_id,
            attempts=1,
        )
