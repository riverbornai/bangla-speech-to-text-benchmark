from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from runner.providers.elevenlabs._common import ElevenLabsProvider


class ElevenLabsStream(ElevenLabsProvider):
    """`text_to_speech.stream()` -> POST /v1/text-to-speech/{voice_id}/stream: audio arrives as it renders."""

    mode = "stream"

    def _request(self, **kwargs: Any) -> Iterator[bytes]:
        return self._client.text_to_speech.stream(**kwargs)
