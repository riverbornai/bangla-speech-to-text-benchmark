from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from runner.providers.elevenlabs._common import ElevenLabsProvider


class ElevenLabsBatch(ElevenLabsProvider):
    """`text_to_speech.convert()` -> POST /v1/text-to-speech/{voice_id}: the clip is rendered, then sent."""

    mode = "batch"

    def _request(self, **kwargs: Any) -> Iterator[bytes]:
        return self._client.text_to_speech.convert(**kwargs)
