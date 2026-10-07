from __future__ import annotations

import io
import json
import time
import wave
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest

from runner.config import ConfigError, load_provider_config
from runner.providers import base
from runner.providers.base import ProviderError
from runner.providers.openai_tts import (
    OpenAIBatch,
    OpenAIStream,
    OpenAITTSProvider,
    create,
    parse_output_format,
)

# The `openai` SDK talks through `httpx2`, which `respx` cannot mock: inject a mock transport instead.
httpx2 = pytest.importorskip("httpx2")
openai = pytest.importorskip("openai")

TEXT = "স্কুলটি এখান থেকে ৫ কি.মি. দূরে।"
PCM = b"\x01\x00" * 12000  # 0.5 s at 24 kHz
HEADERS = {"x-request-id": "req_ok"}


def _wav(pcm: bytes = PCM) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(pcm)
    return buf.getvalue()


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    path = tmp_path / "providers.yaml"
    path.write_text(
        """
providers:
  openai:
    model: gpt-4o-mini-tts
    voice: {id: alloy, name: alloy}
    output_format: wav_24000
    stream: {output_format: pcm_24000}
    max_chars: 20
  unverified:
    model: VERIFY_model
    voice: {id: VERIFY_voice}
    output_format: wav_24000
  tuned:
    model: gpt-4o-mini-tts
    voice: {id: alloy}
    output_format: wav_24000
    voice_settings: {speed: 1.5}
""",
        encoding="utf-8",
    )
    return path


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(base, "sleep", lambda _: None)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")


def _provider(cls, config_path: Path, handler: Callable) -> tuple[OpenAITTSProvider, list]:
    """A real provider whose SDK client is wired to a mock transport; returns (provider, requests seen)."""
    seen: list = []

    def recording(request):
        seen.append(request)
        return handler(request)

    mode = "stream" if cls is OpenAIStream else "batch"
    provider = cls(load_provider_config(config_path, "openai", mode), api_key="test-key")
    provider._client = openai.OpenAI(
        api_key="test-key",
        max_retries=0,
        http_client=httpx2.Client(transport=httpx2.MockTransport(recording)),
    )
    return provider, seen


def _ok(content: bytes | None = None):
    return lambda request: httpx2.Response(200, content=content or _wav(), headers=HEADERS)


def test_batch_sends_exact_text_and_defaults_only(config_path: Path) -> None:
    p, seen = _provider(OpenAIBatch, config_path, _ok())
    result = p.synthesize(TEXT)

    (req,) = seen
    assert req.url.path == "/v1/audio/speech" and req.headers["authorization"] == "Bearer test-key"
    # Exactly these fields: no `instructions`, no `speed`, no language, no stream_format.
    assert json.loads(req.content) == {
        "model": "gpt-4o-mini-tts",
        "voice": "alloy",
        "input": TEXT,
        "response_format": "wav",
    }
    assert result.audio == _wav() and result.format == "wav" and result.sample_rate == 24000
    assert result.ttfb_ms is None and result.total_ms > 0  # batch: no TTFB
    assert result.request_id == "req_ok" and result.billed_chars == len(TEXT) and result.attempts == 1


def test_stream_ttfb_is_first_chunk_and_pcm_becomes_wav(config_path: Path) -> None:
    def slow_body():
        yield PCM[:8000]
        time.sleep(0.05)
        yield PCM[8000:]

    p, seen = _provider(
        OpenAIStream, config_path, lambda r: httpx2.Response(200, content=slow_body(), headers=HEADERS)
    )
    result = p.synthesize(TEXT)

    assert json.loads(seen[0].content)["response_format"] == "pcm"  # stream asks for raw PCM
    assert p.mode == "stream" and 0 <= result.ttfb_ms <= result.total_ms
    assert result.total_ms - result.ttfb_ms >= 50  # TTFB is the first chunk, not the whole body
    assert result.format == "wav" and result.request_id == "req_ok"
    with wave.open(io.BytesIO(result.audio)) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()) == (24000, 1, 2, 12000)


def test_retries_429_and_5xx_then_succeeds(config_path: Path) -> None:
    outcomes = [
        httpx2.Response(429, json={"error": {"code": "rate_limit_exceeded"}}, headers={"retry-after": "1"}),
        httpx2.Response(503),
        httpx2.Response(200, content=_wav(), headers=HEADERS),
    ]
    p, seen = _provider(OpenAIBatch, config_path, lambda r: outcomes.pop(0))
    assert p.synthesize(TEXT).attempts == 3
    assert len(seen) == 3  # the SDK's own retries are disabled


def test_does_not_retry_4xx_and_hides_message(config_path: Path) -> None:
    body = {
        "error": {
            "message": "Incorrect API key: sk-secret",
            "type": "invalid_request_error",
            "code": "invalid_api_key",
        }
    }
    p, seen = _provider(
        OpenAIBatch,
        config_path,
        lambda r: httpx2.Response(401, json=body, headers={"x-request-id": "req_err"}),
    )
    with pytest.raises(ProviderError) as exc:
        p.synthesize(TEXT)
    assert len(seen) == 1
    assert exc.value.status == 401 and str(exc.value) == "invalid_api_key"
    assert exc.value.request_id == "req_err" and "secret" not in str(exc.value)


def test_error_without_a_code_falls_back_to_the_http_status(config_path: Path) -> None:
    p, _ = _provider(OpenAIBatch, config_path, lambda r: httpx2.Response(400, text="nope"))
    with pytest.raises(ProviderError) as exc:
        p.synthesize(TEXT)
    assert exc.value.status == 400 and str(exc.value) == "http_400"


def test_gives_up_after_max_attempts(config_path: Path) -> None:
    p, seen = _provider(OpenAIBatch, config_path, lambda r: httpx2.Response(500))
    with pytest.raises(ProviderError) as exc:
        p.synthesize(TEXT)
    assert len(seen) == base.MAX_ATTEMPTS and exc.value.attempts == base.MAX_ATTEMPTS


def test_transport_failure_is_a_retryable_error_without_status(config_path: Path) -> None:
    def down(request):
        raise httpx2.ConnectError("connection refused")

    p, seen = _provider(OpenAIBatch, config_path, down)
    with pytest.raises(ProviderError) as exc:
        p.synthesize(TEXT)
    assert exc.value.status is None and exc.value.retryable and str(exc.value) == "APIConnectionError"
    assert len(seen) == base.MAX_ATTEMPTS


def test_empty_audio_fails(config_path: Path) -> None:
    p, _ = _provider(OpenAIBatch, config_path, lambda r: httpx2.Response(200, content=b"", headers=HEADERS))
    with pytest.raises(ProviderError, match="empty_audio"):
        p.synthesize(TEXT)


def test_stream_empty_audio_fails(config_path: Path) -> None:
    p, _ = _provider(OpenAIStream, config_path, lambda r: httpx2.Response(200, content=b"", headers=HEADERS))
    with pytest.raises(ProviderError, match="empty_audio"):
        p.synthesize(TEXT)


def test_supports_respects_max_chars(config_path: Path) -> None:
    p, _ = _provider(OpenAIBatch, config_path, _ok())
    item = lambda n: SimpleNamespace(text="ক" * n)  # noqa: E731
    assert p.supports(item(20)) and not p.supports(item(21))


def test_verify_placeholders_are_rejected(config_path: Path) -> None:
    with pytest.raises(ConfigError, match="model"):
        load_provider_config(config_path, "unverified")


def test_voice_settings_are_rejected(config_path: Path) -> None:
    with pytest.raises(ConfigError, match="voice_settings"):
        OpenAIBatch(load_provider_config(config_path, "tuned"), api_key="k")


def test_parse_output_format() -> None:
    assert parse_output_format("wav_24000") == ("wav", 24000)
    assert parse_output_format("pcm_24000") == ("pcm", 24000)
    with pytest.raises(ConfigError):
        parse_output_format("mp3_24000")


def test_create_needs_an_api_key_and_picks_the_mode(
    config_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert isinstance(create(load_provider_config(config_path, "openai", "batch")), OpenAIBatch)
    assert isinstance(create(load_provider_config(config_path, "openai", "stream")), OpenAIStream)
    monkeypatch.delenv("OPENAI_API_KEY")
    with pytest.raises(ConfigError, match="OPENAI_API_KEY"):
        create(load_provider_config(config_path, "openai", "batch"))
