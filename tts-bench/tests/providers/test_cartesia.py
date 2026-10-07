from __future__ import annotations

import base64
import io
import json
import time
import wave
from pathlib import Path

import httpx
import pytest
import respx

from runner.config import ConfigError, load_provider_config
from runner.dataset import DatasetItem
from runner.providers import base
from runner.providers.base import ProviderError
from runner.providers.cartesia import (
    CartesiaBatch,
    CartesiaProvider,
    CartesiaStream,
    create,
    parse_output_format,
)

BYTES_URL = "https://api.cartesia.ai/tts/bytes"
SSE_URL = "https://api.cartesia.ai/tts/sse"
TEXT = "স্কুলটি এখান থেকে ৫ কি.মি. দূরে।"
PCM = b"\x01\x00" * 12000  # 0.5 s at 24 kHz


def _wav(pcm: bytes = PCM, rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def _sse(*events: dict) -> bytes:
    return b"".join(b"event: message\ndata: " + json.dumps(e).encode() + b"\n\n" for e in events)


def _chunk(pcm: bytes) -> dict:
    return {"type": "chunk", "data": base64.b64encode(pcm).decode(), "done": False, "status_code": 206}


DONE = {"type": "done", "done": True, "status_code": 200}


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    path = tmp_path / "providers.yaml"
    path.write_text(
        """
providers:
  cartesia:
    language_code: bn
    model: sonic-3.6
    voice: {id: 11111111-2222-3333-4444-555555555555, name: bn-voice}
    output_format: wav_24000
    stream: {output_format: pcm_24000}
    max_chars: 20
  nolimit:
    model: sonic-3.6
    voice: {id: v1}
    output_format: wav_24000
  unverified:
    model: sonic-3.6
    voice: {id: VERIFY_voice_id}
    output_format: wav_24000
""",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def provider(config_path: Path) -> CartesiaProvider:
    return CartesiaBatch(load_provider_config(config_path, "cartesia"), api_key="test-key")


@pytest.fixture
def stream_provider(config_path: Path) -> CartesiaProvider:
    return CartesiaStream(load_provider_config(config_path, "cartesia", "stream"), api_key="test-key")


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(base, "sleep", lambda _: None)


def _item(text: str) -> DatasetItem:
    return DatasetItem("BN-X-001", text, None, (), "plain", None, None, 1)


@respx.mock
def test_batch_sends_exact_text_voice_language_and_wav_format(provider: CartesiaProvider) -> None:
    route = respx.post(BYTES_URL).mock(return_value=httpx.Response(200, content=_wav()))
    result = provider.synthesize(TEXT)

    req = route.calls.last.request
    assert req.headers["authorization"] == "Bearer test-key"
    assert req.headers["cartesia-version"] == "2026-08-14"  # sent by the SDK
    assert json.loads(req.content) == {
        "model_id": "sonic-3.6",
        "transcript": TEXT,  # unchanged
        "voice": {"mode": "id", "id": "11111111-2222-3333-4444-555555555555"},
        "language": "bn",  # `language`, never `locale`
        "output_format": {"container": "wav", "encoding": "pcm_s16le", "sample_rate": 24000},
    }
    assert result.format == "wav" and result.sample_rate == 24000
    assert result.ttfb_ms is None and result.total_ms > 0  # batch: no TTFB
    assert result.billed_chars == len(TEXT) and result.attempts == 1 and result.request_id is None
    with wave.open(io.BytesIO(result.audio)) as w:
        assert w.getnframes() == 12000


@respx.mock
def test_batch_empty_body_fails(provider: CartesiaProvider) -> None:
    respx.post(BYTES_URL).mock(return_value=httpx.Response(200, content=b""))
    with pytest.raises(ProviderError, match="empty_audio"):
        provider.synthesize(TEXT)


@respx.mock
def test_stream_asks_for_raw_pcm_parses_sse_and_wraps_wav(stream_provider: CartesiaProvider) -> None:
    route = respx.post(SSE_URL).mock(
        return_value=httpx.Response(
            200,
            content=_sse(_chunk(PCM[:8000]), _chunk(PCM[8000:]), DONE),
            headers={"content-type": "text/event-stream"},
        )
    )
    result = stream_provider.synthesize(TEXT)

    body = json.loads(route.calls.last.request.content)
    assert body["transcript"] == TEXT and body["language"] == "bn" and body["model_id"] == "sonic-3.6"
    assert body["output_format"] == {"container": "raw", "encoding": "pcm_s16le", "sample_rate": 24000}
    assert stream_provider.mode == "stream" and result.format == "wav" and result.sample_rate == 24000
    assert 0 <= result.ttfb_ms <= result.total_ms
    with wave.open(io.BytesIO(result.audio)) as w:  # raw PCM wrapped into a valid WAV
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()) == (24000, 1, 2, 12000)
        assert w.readframes(12000) == PCM


def test_stream_ttfb_is_first_chunk_not_whole_body(
    stream_provider: CartesiaProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    def slow(**_kw):
        class Event:
            def __init__(self, type_: str, data: str | None = None) -> None:
                self.type, self.data = type_, data

        yield Event("chunk", base64.b64encode(b"ab").decode())
        time.sleep(0.05)
        yield Event("chunk", "")  # empty chunks do not count as the first audio
        yield Event("chunk", base64.b64encode(b"cd").decode())
        yield Event("done")

    monkeypatch.setattr(stream_provider._client.tts, "generate_sse", slow)
    result = stream_provider.synthesize(TEXT)
    with wave.open(io.BytesIO(result.audio)) as w:
        assert w.readframes(2) == b"abcd"
    assert result.total_ms - result.ttfb_ms >= 50


@respx.mock
def test_stream_in_band_error_event_keeps_only_the_short_code(stream_provider: CartesiaProvider) -> None:
    event = {
        "type": "error", "done": True, "status_code": 404, "error_code": "voice_not_found",
        "title": "Voice", "message": "secret details", "request_id": "req-5",
    }  # fmt: skip
    route = respx.post(SSE_URL).mock(return_value=httpx.Response(200, content=_sse(event)))
    with pytest.raises(ProviderError) as exc:
        stream_provider.synthesize(TEXT)
    assert route.call_count == 1  # 404 is not retried
    assert exc.value.status == 404 and str(exc.value) == "voice_not_found" and exc.value.request_id == "req-5"


@respx.mock
def test_stream_empty_audio_fails(stream_provider: CartesiaProvider) -> None:
    respx.post(SSE_URL).mock(return_value=httpx.Response(200, content=_sse(DONE)))
    with pytest.raises(ProviderError, match="empty_audio"):
        stream_provider.synthesize(TEXT)


@respx.mock
def test_retries_429_and_5xx_then_succeeds(provider: CartesiaProvider) -> None:
    route = respx.post(BYTES_URL).mock(
        side_effect=[
            httpx.Response(429, json={"error_code": "rate_limit"}, headers={"retry-after": "1"}),
            httpx.Response(503),
            httpx.Response(200, content=_wav()),
        ]
    )
    assert provider.synthesize(TEXT).attempts == 3
    assert route.call_count == 3  # the SDK's own retries are disabled


@respx.mock
def test_retries_transport_errors(provider: CartesiaProvider) -> None:
    route = respx.post(BYTES_URL).mock(
        side_effect=[httpx.ConnectTimeout("t"), httpx.Response(200, content=_wav())]
    )
    assert provider.synthesize(TEXT).attempts == 2
    assert route.call_count == 2


@respx.mock
def test_does_not_retry_4xx_and_hides_body(provider: CartesiaProvider) -> None:
    route = respx.post(BYTES_URL).mock(
        return_value=httpx.Response(
            401, json={"error_code": "invalid_api_key", "message": "secret", "request_id": "req-1"}
        )
    )
    with pytest.raises(ProviderError) as exc:
        provider.synthesize(TEXT)
    assert route.call_count == 1
    assert exc.value.status == 401 and str(exc.value) == "invalid_api_key" and exc.value.request_id == "req-1"
    assert "secret" not in str(exc.value)


@respx.mock
def test_error_without_a_code_falls_back_to_the_status(provider: CartesiaProvider) -> None:
    respx.post(BYTES_URL).mock(return_value=httpx.Response(400, text="not json"))
    with pytest.raises(ProviderError) as exc:
        provider.synthesize(TEXT)
    assert exc.value.status == 400 and str(exc.value) == "http_400" and exc.value.request_id is None


@respx.mock
def test_gives_up_after_max_attempts(provider: CartesiaProvider) -> None:
    route = respx.post(BYTES_URL).mock(return_value=httpx.Response(500))
    with pytest.raises(ProviderError) as exc:
        provider.synthesize(TEXT)
    assert route.call_count == base.MAX_ATTEMPTS and exc.value.attempts == base.MAX_ATTEMPTS


def test_supports_respects_max_chars_when_set(provider: CartesiaProvider, config_path: Path) -> None:
    assert provider.supports(_item("ক" * 20)) and not provider.supports(_item("ক" * 21))
    unlimited = CartesiaBatch(load_provider_config(config_path, "nolimit"), api_key="k")
    assert unlimited.supports(_item("ক" * 100_000))  # Cartesia documents no maximum


def test_verify_voice_placeholder_is_rejected(config_path: Path) -> None:
    with pytest.raises(ConfigError, match="voice.id"):
        load_provider_config(config_path, "unverified")


def test_parse_output_format() -> None:
    assert parse_output_format("wav_24000") == ("wav", 24000)
    assert parse_output_format("pcm_24000") == ("pcm", 24000)
    with pytest.raises(ConfigError):
        parse_output_format("mp3_44100_128")


def test_create_needs_the_api_key(config_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CARTESIA_API_KEY", raising=False)
    with pytest.raises(ConfigError, match="CARTESIA_API_KEY"):
        create(load_provider_config(config_path, "cartesia"))
    monkeypatch.setenv("CARTESIA_API_KEY", "k")
    assert isinstance(create(load_provider_config(config_path, "cartesia")), CartesiaBatch)
    assert isinstance(create(load_provider_config(config_path, "cartesia", "stream")), CartesiaStream)
