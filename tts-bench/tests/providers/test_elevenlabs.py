from __future__ import annotations

import json
import time
from pathlib import Path

import httpx
import pytest
import respx

from runner.config import ConfigError, load_provider_config
from runner.dataset import DatasetItem
from runner.providers import base
from runner.providers.base import ProviderError
from runner.providers.elevenlabs import (
    ElevenLabsBatch,
    ElevenLabsProvider,
    ElevenLabsStream,
    create,
    parse_output_format,
)

URL = "https://api.elevenlabs.io/v1/text-to-speech/voice123"
TEXT = "স্কুলটি এখান থেকে ৫ কি.মি. দূরে।"
MP3 = b"ID3" + b"\x00" * 997


@pytest.fixture
def provider(providers_yaml: Path) -> ElevenLabsProvider:
    return ElevenLabsBatch(load_provider_config(providers_yaml, "elevenlabs"), api_key="test-key")


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(base, "sleep", lambda _: None)


def _item(text: str) -> DatasetItem:
    return DatasetItem("BN-X-001", text, None, (), "plain", None, None, 1)


@respx.mock
def test_convert_sends_text_model_language_and_voice_settings(provider: ElevenLabsProvider) -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(200, content=MP3))
    result = provider.synthesize(TEXT)

    req = route.calls.last.request
    assert req.headers["xi-api-key"] == "test-key"
    assert req.url.params["output_format"] == "mp3_44100_128"
    body = json.loads(req.content)
    assert body["text"] == TEXT
    assert body["model_id"] == "eleven_v4"
    assert body["language_code"] == "bn"
    assert body["voice_settings"]["stability"] == 0.1
    assert body["voice_settings"]["similarity_boost"] == 0.75
    assert result.audio == MP3
    assert result.format == "mp3" and result.sample_rate == 44100
    assert result.billed_chars == len(TEXT)
    assert result.ttfb_ms is None and result.total_ms > 0  # batch: no TTFB
    assert result.attempts == 1


@respx.mock
def test_retries_429_and_5xx_then_succeeds(provider: ElevenLabsProvider) -> None:
    route = respx.post(URL).mock(
        side_effect=[
            httpx.Response(429, json={"detail": {"status": "too_many_concurrent_requests"}}),
            httpx.Response(503),
            httpx.Response(200, content=MP3),
        ]
    )
    assert provider.synthesize(TEXT).attempts == 3
    assert route.call_count == 3  # SDK's own retries are disabled


@respx.mock
def test_does_not_retry_4xx_and_hides_body(provider: ElevenLabsProvider) -> None:
    route = respx.post(URL).mock(
        return_value=httpx.Response(401, json={"detail": {"status": "invalid_api_key", "message": "secret"}})
    )
    with pytest.raises(ProviderError) as exc:
        provider.synthesize(TEXT)
    assert route.call_count == 1
    assert exc.value.status == 401
    assert str(exc.value) == "invalid_api_key"


@respx.mock
def test_gives_up_after_max_attempts(provider: ElevenLabsProvider) -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(500))
    with pytest.raises(ProviderError) as exc:
        provider.synthesize(TEXT)
    assert route.call_count == base.MAX_ATTEMPTS
    assert exc.value.attempts == base.MAX_ATTEMPTS


def test_supports_respects_max_chars(provider: ElevenLabsProvider) -> None:
    assert provider.supports(_item("ক" * 20))
    assert not provider.supports(_item("ক" * 21))


def test_verify_placeholders_are_rejected(providers_yaml: Path) -> None:
    with pytest.raises(ConfigError, match="model"):
        load_provider_config(providers_yaml, "unverified")


def test_parse_output_format() -> None:
    assert parse_output_format("mp3_44100_128") == ("mp3", 44100)
    assert parse_output_format("pcm_24000") == ("pcm", 24000)


def test_stream_ttfb_is_first_chunk_not_whole_body(
    providers_yaml: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = ElevenLabsStream(load_provider_config(providers_yaml, "elevenlabs", "stream"), api_key="k")

    def slow_stream():
        yield b"ab"
        time.sleep(0.05)
        yield b""
        yield b"cd"

    monkeypatch.setattr(provider._client.text_to_speech, "stream", lambda **_: slow_stream())
    result = provider.synthesize(TEXT)
    assert result.audio == b"abcd"
    assert result.total_ms - result.ttfb_ms >= 50


@respx.mock
def test_stream_mode_calls_stream_endpoint(providers_yaml: Path) -> None:
    provider = ElevenLabsStream(load_provider_config(providers_yaml, "elevenlabs", "stream"), api_key="k")
    route = respx.post(f"{URL}/stream").mock(return_value=httpx.Response(200, content=MP3))
    result = provider.synthesize(TEXT)

    body = json.loads(route.calls.last.request.content)
    assert body["text"] == TEXT and body["model_id"] == "eleven_v4" and body["language_code"] == "bn"
    assert route.calls.last.request.url.params["output_format"] == "mp3_44100_128"
    assert result.audio == MP3 and provider.mode == "stream"
    assert 0 <= result.ttfb_ms <= result.total_ms


def test_create_picks_class_by_mode(providers_yaml: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    assert isinstance(create(load_provider_config(providers_yaml, "elevenlabs")), ElevenLabsBatch)
    assert isinstance(create(load_provider_config(providers_yaml, "elevenlabs", "stream")), ElevenLabsStream)


def test_mode_block_overrides_config(tmp_path: Path) -> None:
    path = tmp_path / "providers.yaml"
    path.write_text(
        "providers:\n  elevenlabs:\n    model: m\n    voice: {id: v}\n    output_format: mp3_44100_128\n"
        "    stream: {output_format: pcm_24000}\n",
        encoding="utf-8",
    )
    assert load_provider_config(path, "elevenlabs").output_format == "mp3_44100_128"
    stream = load_provider_config(path, "elevenlabs", "stream")
    assert stream.output_format == "pcm_24000" and stream.mode == "stream"
