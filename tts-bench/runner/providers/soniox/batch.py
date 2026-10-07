from __future__ import annotations

import time

from runner.providers.base import ProviderError, SynthesisResult
from runner.providers.soniox._common import AUDIO_FORMATS, SonioxProvider, sdk_errors


class SonioxBatch(SonioxProvider):
    """`tts.generate()` -> POST https://tts-rt.soniox.com/tts: the clip is rendered, then sent whole."""

    mode = "batch"

    def _attempt(self, text: str) -> SynthesisResult:
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
