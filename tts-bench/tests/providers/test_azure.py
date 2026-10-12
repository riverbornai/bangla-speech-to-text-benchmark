from __future__ import annotations

import io
import time
import wave
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import respx

from runner.config import ConfigError, load_provider_config
from runner.providers.azure import AzureBatch, AzureStream, create, parse_output_format, to_ssml
from runner.providers.base import ProviderError

URL = "https://southeastasia.tts.speech.microsoft.com/cognitiveservices/v1"
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
  azure:
    language_code: bn-BD
    model: neural
    voice: {id: bn-BD-NabanitaNeural, name: bn-BD-NabanitaNeural}
    output_format: wav_24000
    max_chars: 20
""",
        encoding="utf-8",
    )
    return path


def _provider(cls, config_path: Path):
    mode = "stream" if cls is AzureStream else "batch"
    return cls(load_provider_config(config_path, "azure", mode), "secret-key", "southeastasia")


def _item(text: str):
    return SimpleNamespace(text=text)


@respx.mock
def test_batch_posts_ssml_and_returns_wav(config_path: Path) -> None:
    route = respx.post(URL).respond(200, content=_wav(), headers={"x-requestid": "rid-1"})
    result = _provider(AzureBatch, config_path).synthesize(TEXT)

    req = route.calls[0].request
    assert req.headers["Ocp-Apim-Subscription-Key"] == "secret-key"
    assert req.headers["Content-Type"] == "application/ssml+xml"
    assert req.headers["X-Microsoft-OutputFormat"] == "riff-24khz-16bit-mono-pcm"
    body = req.content.decode("utf-8")
    assert f'<voice name="bn-BD-NabanitaNeural">{TEXT}</voice>' in body and 'xml:lang="bn-BD"' in body
    assert result.format == "wav" and result.sample_rate == 24000
    assert result.ttfb_ms is None and result.total_ms > 0
    assert result.request_id == "rid-1" and result.billed_chars == len(TEXT)
    with wave.open(io.BytesIO(result.audio)) as w:
        assert w.getnframes() == 12000


def test_text_is_xml_escaped_but_breaks_pass_through() -> None:
    ssml = to_ssml('a & b < c <break time="700ms"/> d', "v", "bn-BD")
    assert "a &amp; b &lt; c" in ssml and '<break time="700ms"/>' in ssml
    # only the exact break form is markup
    assert "&lt;break time=" in to_ssml('<break time="x"/>', "v", "bn-BD")
    assert "&lt;laugh&gt;" in to_ssml("<laugh>", "v", "bn-BD")


@respx.mock
def test_stream_ttfb_is_first_chunk(config_path: Path) -> None:
    class Slow(httpx.SyncByteStream):
        def __iter__(self):
            data = _wav()
            yield data[:8000]
            time.sleep(0.05)
            yield data[8000:]

    respx.post(URL).mock(return_value=httpx.Response(200, stream=Slow()))
    p = _provider(AzureStream, config_path)
    result = p.synthesize(TEXT)
    assert p.mode == "stream" and 0 <= result.ttfb_ms <= result.total_ms
    assert result.total_ms - result.ttfb_ms >= 50
    with wave.open(io.BytesIO(result.audio)) as w:
        assert w.getnframes() == 12000


@respx.mock
@pytest.mark.parametrize("cls", [AzureBatch, AzureStream])
@pytest.mark.parametrize("status", [401, 429, 500])
def test_errors_are_not_retried_and_body_is_hidden(config_path: Path, cls, status: int) -> None:
    route = respx.post(URL).respond(status, text="SECRET-BODY", headers={"x-requestid": "rid-2"})
    with pytest.raises(ProviderError) as exc:
        _provider(cls, config_path).synthesize(TEXT)
    assert route.call_count == 1
    assert exc.value.status == status and "SECRET-BODY" not in str(exc.value)


@respx.mock
def test_transport_error_becomes_provider_error(config_path: Path) -> None:
    respx.post(URL).mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(ProviderError) as exc:
        _provider(AzureBatch, config_path).synthesize(TEXT)
    assert exc.value.status is None and "ConnectError" in str(exc.value)


@respx.mock
def test_empty_audio_fails(config_path: Path) -> None:
    respx.post(URL).respond(200, content=b"")
    with pytest.raises(ProviderError, match="empty_audio"):
        _provider(AzureBatch, config_path).synthesize(TEXT)


def test_supports_respects_max_chars(config_path: Path) -> None:
    p = _provider(AzureBatch, config_path)
    assert p.supports(_item("ক" * 20)) and not p.supports(_item("ক" * 21))


def test_parse_output_format() -> None:
    assert parse_output_format("wav_24000") == ("wav", 24000)
    with pytest.raises(ConfigError):
        parse_output_format("mp3_24000")


def test_create_needs_key_and_region(config_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = load_provider_config(config_path, "azure", "batch")
    monkeypatch.delenv("AZURE_SPEECH_KEY", raising=False)
    monkeypatch.setenv("AZURE_SPEECH_REGION", "southeastasia")
    with pytest.raises(ConfigError):
        create(config)
    monkeypatch.setenv("AZURE_SPEECH_KEY", "k")
    monkeypatch.delenv("AZURE_SPEECH_REGION")
    with pytest.raises(ConfigError):
        create(config)
    monkeypatch.setenv("AZURE_SPEECH_REGION", "southeastasia")
    assert isinstance(create(config), AzureBatch)
