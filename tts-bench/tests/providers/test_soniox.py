from __future__ import annotations

import io
import json
import time
import wave
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import respx
from soniox.errors import SonioxRealtimeError

from runner.config import ConfigError, load_provider_config
from runner.dataset import DatasetItem
from runner.providers import base
from runner.providers.base import ProviderError
from runner.providers.soniox import (
    SonioxBatch,
    SonioxProvider,
    SonioxStream,
    create,
    parse_output_format,
)

URL = "https://tts-rt.soniox.com/tts"
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


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    path = tmp_path / "providers.yaml"
    path.write_text(
        """
providers:
  soniox:
    language_code: bn
    model: tts-rt-v2
    voice: {id: Adrian, name: Adrian}
    output_format: wav_24000
    stream: {output_format: pcm_24000}
    max_chars: 20
    price: {unit: VERIFY, usd_per_unit: VERIFY, price_checked: null}
  unverified:
    model: VERIFY_model
    voice: {id: VERIFY_voice}
    output_format: wav_24000
""",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def provider(config_path: Path) -> SonioxProvider:
    return SonioxBatch(load_provider_config(config_path, "soniox"), api_key="test-key")


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(base, "sleep", lambda _: None)


def _item(text: str) -> DatasetItem:
    return DatasetItem("BN-X-001", text, None, (), "plain", None, None, 1)


def _error(status: int, error_type: str, **extra) -> httpx.Response:
    body = {"status_code": status, "error_type": error_type, "message": "secret detail", **extra}
    return httpx.Response(status, json=body)


@respx.mock
def test_batch_sends_exact_text_and_returns_wav(provider: SonioxProvider) -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(200, content=_wav()))
    result = provider.synthesize(TEXT)

    req = route.calls.last.request
    assert req.headers["authorization"] == "Bearer test-key"
    assert json.loads(req.content) == {
        "model": "tts-rt-v2",
        "language": "bn",
        "voice": "Adrian",
        "audio_format": "wav",
        "sample_rate": 24000,
        "text": TEXT,  # byte-for-byte; no speed / reduce_silence in the baseline
    }
    assert result.format == "wav" and result.sample_rate == 24000 and provider.mode == "batch"
    assert result.ttfb_ms is None and result.total_ms > 0  # batch: no TTFB
    assert result.request_id is None and result.billed_chars == len(TEXT) and result.attempts == 1
    with wave.open(io.BytesIO(result.audio)) as w:
        assert (w.getframerate(), w.getnframes()) == (24000, 12000)


@respx.mock
def test_batch_with_pcm_format_is_wrapped_as_wav(config_path: Path) -> None:
    config = load_provider_config(config_path, "soniox", "stream")  # pcm_24000
    provider = SonioxBatch(config, api_key="k")
    route = respx.post(URL).mock(return_value=httpx.Response(200, content=PCM))
    result = provider.synthesize(TEXT)

    assert json.loads(route.calls.last.request.content)["audio_format"] == "pcm_s16le"
    with wave.open(io.BytesIO(result.audio)) as w:
        assert (w.getframerate(), w.getnframes()) == (24000, 12000)


@respx.mock
def test_empty_audio_fails(provider: SonioxProvider) -> None:
    respx.post(URL).mock(return_value=httpx.Response(200, content=b""))
    with pytest.raises(ProviderError, match="empty_audio"):
        provider.synthesize(TEXT)


@respx.mock
def test_retries_429_5xx_and_transport_errors_then_succeeds(provider: SonioxProvider) -> None:
    route = respx.post(URL).mock(
        side_effect=[
            _error(429, "limit_exceeded"),
            httpx.Response(503, text="<html>bad gateway</html>"),  # no JSON body at all
            httpx.ConnectError("boom"),
            httpx.Response(200, content=_wav()),
        ]
    )
    assert provider.synthesize(TEXT).attempts == 4
    assert route.call_count == 4  # the SDK does not retry on its own


@respx.mock
def test_does_not_retry_4xx_and_hides_body(provider: SonioxProvider) -> None:
    route = respx.post(URL).mock(return_value=_error(401, "unauthenticated", request_id="req-9"))
    with pytest.raises(ProviderError) as exc:
        provider.synthesize(TEXT)
    assert route.call_count == 1
    assert exc.value.status == 401 and exc.value.request_id == "req-9"
    assert str(exc.value) == "unauthenticated"  # error_type only, never the message


@respx.mock
def test_402_and_non_json_errors_map_to_short_codes(provider: SonioxProvider) -> None:
    respx.post(URL).mock(return_value=_error(402, "organization_balance_exhausted"))
    with pytest.raises(ProviderError) as exc:
        provider.synthesize(TEXT)
    assert exc.value.status == 402 and str(exc.value) == "organization_balance_exhausted"

    respx.post(URL).mock(return_value=httpx.Response(400, text="not json"))
    with pytest.raises(ProviderError) as exc:
        provider.synthesize(TEXT)
    assert exc.value.status == 400 and str(exc.value) == "http_400"


@respx.mock
def test_gives_up_after_max_attempts_and_reads_retry_after(provider: SonioxProvider) -> None:
    limited = _error(429, "limit_exceeded")
    limited.headers["retry-after"] = "3"
    route = respx.post(URL).mock(return_value=limited)
    with pytest.raises(ProviderError) as exc:
        provider.synthesize(TEXT)
    assert route.call_count == base.MAX_ATTEMPTS
    assert exc.value.attempts == base.MAX_ATTEMPTS and exc.value.retry_after == 3.0


def test_supports_respects_max_chars(provider: SonioxProvider) -> None:
    assert provider.supports(_item("ক" * 20))
    assert not provider.supports(_item("ক" * 21))


def test_verify_placeholders_are_rejected(config_path: Path) -> None:
    with pytest.raises(ConfigError, match="model"):
        load_provider_config(config_path, "unverified")


def test_parse_output_format() -> None:
    assert parse_output_format("wav_24000") == ("wav", 24000)
    assert parse_output_format("pcm_24000") == ("pcm", 24000)
    for bad in ("mp3_24000", "wav_22050", "wav", "pcm_abc"):
        with pytest.raises(ConfigError):
            parse_output_format(bad)


def test_language_code_is_required(config_path: Path) -> None:
    config = load_provider_config(config_path, "soniox")
    with pytest.raises(ConfigError, match="language_code"):
        SonioxBatch(type(config)(**{**config.__dict__, "language_code": None}), api_key="k")


def test_create_needs_the_api_key(config_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SONIOX_API_KEY", raising=False)
    with pytest.raises(ConfigError, match="SONIOX_API_KEY"):
        create(load_provider_config(config_path, "soniox"))

    monkeypatch.setenv("SONIOX_API_KEY", "k")
    assert isinstance(create(load_provider_config(config_path, "soniox", "batch")), SonioxBatch)
    assert isinstance(create(load_provider_config(config_path, "soniox", "stream")), SonioxStream)


def test_stream_mode_needs_pcm(config_path: Path) -> None:
    config = load_provider_config(config_path, "soniox", "batch")  # wav_24000
    with pytest.raises(ConfigError, match="pcm_<rate>"):
        SonioxStream(type(config)(**{**config.__dict__, "mode": "stream"}), api_key="k")


class FakeRealtime:
    """Stands in for `client.realtime.tts`: records the config and sent text, plays back audio chunks."""

    def __init__(self, chunks) -> None:
        self.chunks = chunks
        self.config = None
        self.sent: list[tuple[str, bool]] = []
        self.connects = 0

    @contextmanager
    def connect(self, *, config):
        self.connects += 1
        self.config = config
        outer = self
        yield SimpleNamespace(
            send_text_chunk=lambda text, *, text_end=False: outer.sent.append((text, text_end)),
            receive_audio_chunks=lambda: outer.chunks(),
        )


def _stream(config_path: Path, chunks) -> tuple[SonioxStream, FakeRealtime]:
    provider = SonioxStream(load_provider_config(config_path, "soniox", "stream"), api_key="k")
    fake = FakeRealtime(chunks)
    provider._client = SimpleNamespace(realtime=SimpleNamespace(tts=fake), close=lambda: None)
    return provider, fake


def test_stream_ttfb_is_first_chunk_and_pcm_is_wrapped(config_path: Path) -> None:
    def chunks():
        yield PCM[:8000]
        time.sleep(0.05)
        yield b""
        yield PCM[8000:]

    provider, fake = _stream(config_path, chunks)
    result = provider.synthesize(TEXT)

    assert provider.mode == "stream" and result.format == "wav" and result.sample_rate == 24000
    assert 0 <= result.ttfb_ms <= result.total_ms and result.total_ms - result.ttfb_ms >= 50
    assert result.request_id is None and result.billed_chars == len(TEXT)
    with wave.open(io.BytesIO(result.audio)) as w:
        assert (w.getframerate(), w.getnframes()) == (24000, 12000)
    # The whole text goes out once, byte-for-byte, and the stream is closed with text_end.
    assert fake.sent == [(TEXT, True)]
    cfg = fake.config
    assert (cfg.model, cfg.language, cfg.voice) == ("tts-rt-v2", "bn", "Adrian")
    assert (cfg.audio_format, cfg.sample_rate) == ("pcm_s16le", 24000)
    assert cfg.stream_id  # a fresh id per request


def test_stream_empty_audio_fails(config_path: Path) -> None:
    provider, _ = _stream(config_path, lambda: iter([b"", b""]))
    with pytest.raises(ProviderError, match="empty_audio"):
        provider.synthesize(TEXT)


def test_stream_server_error_with_code_is_not_retried_when_4xx(config_path: Path) -> None:
    def chunks():
        raise SonioxRealtimeError("Invalid request: secret detail (code 400)")
        yield b""  # pragma: no cover

    provider, fake = _stream(config_path, chunks)
    with pytest.raises(ProviderError) as exc:
        provider.synthesize(TEXT)
    assert fake.connects == 1 and exc.value.status == 400
    assert str(exc.value) == "realtime_error"  # the server's message text is not kept


def test_stream_retries_rate_limits_and_timeouts(config_path: Path) -> None:
    outcomes = [
        SonioxRealtimeError("Too many requests (code 429)"),
        SonioxRealtimeError("Timed out waiting for realtime Text-to-Speech event"),  # no code: transport-like
        None,
    ]

    def chunks():
        outcome = outcomes.pop(0)
        if outcome:
            raise outcome
        yield PCM

    provider, fake = _stream(config_path, chunks)
    assert provider.synthesize(TEXT).attempts == 3
    assert fake.connects == 3
