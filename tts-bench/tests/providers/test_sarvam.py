from __future__ import annotations

import base64
import io
import json
import wave
from pathlib import Path

import httpx
import pytest
import respx

from runner.config import load_provider_config
from runner.dataset import DatasetItem
from runner.main import audio_seconds
from runner.providers import base
from runner.providers.base import ProviderError
from runner.providers.sarvam import SarvamBatch, SarvamProvider, SarvamStream

URL = "https://api.sarvam.ai/text-to-speech"
TEXT = "স্কুলটি এখান থেকে ৫ কি.মি. দূরে।"


def _wav(seconds: float = 0.5, rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    return buf.getvalue()


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    path = tmp_path / "providers.yaml"
    path.write_text(
        """
providers:
  sarvam:
    language_code: bn-IN
    model: bulbul:v3
    voice: {id: shubh, name: shubh}
    output_format: wav_24000
    max_chars: 20
""",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def provider(config_path: Path) -> SarvamProvider:
    return SarvamBatch(load_provider_config(config_path, "sarvam"), api_key="test-key")


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(base, "sleep", lambda _: None)


def _ok(audio: bytes) -> httpx.Response:
    return httpx.Response(200, json={"request_id": "req-9", "audios": [base64.b64encode(audio).decode()]})


@respx.mock
def test_synthesize_sends_exact_text_and_decodes_wav(provider: SarvamProvider) -> None:
    wav = _wav(0.5)
    route = respx.post(URL).mock(return_value=_ok(wav))
    result = provider.synthesize(TEXT)

    req = route.calls.last.request
    assert req.headers["api-subscription-key"] == "test-key"
    expected = {
        "text": TEXT,
        "language_code": "bn-IN",
        "model": "bulbul:v3",
        "speaker": "shubh",
        "output_audio_codec": "wav",
        "speech_sample_rate": 24000,
    }
    assert json.loads(req.content).items() >= expected.items()
    assert result.audio == wav
    assert result.format == "wav" and result.sample_rate == 24000
    assert result.request_id == "req-9"
    assert result.ttfb_ms == result.total_ms  # batch: the whole clip arrives at once
    assert result.billed_chars == len(TEXT)
    assert audio_seconds(result.audio, result.format, result.sample_rate) == 0.5


@respx.mock
def test_retries_429_then_succeeds(provider: SarvamProvider) -> None:
    route = respx.post(URL).mock(side_effect=[httpx.Response(429), httpx.Response(502), _ok(_wav())])
    assert provider.synthesize(TEXT).attempts == 3
    assert route.call_count == 3  # SDK's own retries are disabled


@respx.mock
def test_does_not_retry_4xx_and_hides_body(provider: SarvamProvider) -> None:
    route = respx.post(URL).mock(
        return_value=httpx.Response(
            400, json={"error": {"code": "invalid_request_error", "message": "text too long secret"}}
        )
    )
    with pytest.raises(ProviderError) as exc:
        provider.synthesize(TEXT)
    assert route.call_count == 1
    assert exc.value.status == 400
    assert str(exc.value) == "invalid_request_error"


@respx.mock
def test_rejects_multiple_audios(provider: SarvamProvider) -> None:
    b64 = base64.b64encode(_wav()).decode()
    respx.post(URL).mock(return_value=httpx.Response(200, json={"request_id": "r", "audios": [b64, b64]}))
    with pytest.raises(ProviderError, match="expected 1 audio"):
        provider.synthesize(TEXT)


def test_supports_respects_max_chars(provider: SarvamProvider) -> None:
    item = DatasetItem("BN-X-001", "ক" * 21, None, (), "plain", None, None, 1)
    assert not provider.supports(item)


@respx.mock
def test_stream_mode_returns_raw_audio_bytes(config_path: Path) -> None:
    provider = SarvamStream(load_provider_config(config_path, "sarvam", "stream"), api_key="test-key")
    wav = _wav(0.5)
    route = respx.post(f"{URL}/stream").mock(return_value=httpx.Response(200, content=wav))
    result = provider.synthesize(TEXT)

    body = json.loads(route.calls.last.request.content)
    assert body["text"] == TEXT and body["speaker"] == "shubh" and body["output_audio_codec"] == "wav"
    assert result.audio == wav and provider.mode == "stream"
    assert 0 <= result.ttfb_ms <= result.total_ms
    assert audio_seconds(result.audio, result.format, result.sample_rate) == 0.5


@respx.mock
def test_stream_mode_retries_5xx(config_path: Path) -> None:
    provider = SarvamStream(load_provider_config(config_path, "sarvam", "stream"), api_key="test-key")
    route = respx.post(f"{URL}/stream").mock(
        side_effect=[httpx.Response(503), httpx.Response(200, content=_wav())]
    )
    assert provider.synthesize(TEXT).attempts == 2
    assert route.call_count == 2
