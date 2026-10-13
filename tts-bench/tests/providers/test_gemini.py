from __future__ import annotations

import io
import time
import wave
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from google.genai import errors, types

from runner.config import ConfigError, load_provider_config
from runner.dataset import DatasetItem
from runner.providers.base import ProviderError
from runner.providers.gemini import (
    GeminiBatch,
    GeminiProvider,
    GeminiStream,
    build_parts,
    parse_output_format,
    to_wav,
)

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


def _resp(data: bytes | None, rid: str = "resp-1") -> types.GenerateContentResponse:
    parts = [types.Part(inline_data=types.Blob(data=data, mime_type="audio/wav"))] if data else []
    return types.GenerateContentResponse(
        response_id=rid, candidates=[types.Candidate(content=types.Content(role="model", parts=parts))]
    )


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    path = tmp_path / "providers.yaml"
    path.write_text(
        """
providers:
  gemini:
    language_code: bn-BD
    location: global
    model: gemini-3.8-flash-tts
    voice: {id: Kore, name: Kore}
    output_format: wav_24000
    max_chars: 20
""",
        encoding="utf-8",
    )
    return path


class FakeModels:
    def __init__(self, behaviour) -> None:
        self.behaviour = behaviour
        self.calls: list[dict] = []

    def generate_content(self, **kw):
        self.calls.append(kw)
        return self.behaviour(kw)

    generate_content_stream = generate_content


def _provider(cls, config_path: Path, behaviour, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("google.genai.Client", lambda **_: SimpleNamespace(models=FakeModels(behaviour)))
    mode = "stream" if cls is GeminiStream else "batch"
    return cls(load_provider_config(config_path, "gemini", mode))


def _item(text: str) -> DatasetItem:
    return SimpleNamespace(text=text)  # type: ignore[return-value]


def test_batch_sends_exact_text_and_returns_wav(config_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = _provider(GeminiBatch, config_path, lambda kw: _resp(_wav()), monkeypatch)
    result = p.synthesize(TEXT)

    kw = p._client.models.calls[0]
    assert kw["model"] == "gemini-3.8-flash-tts"
    assert kw["contents"] == [{"role": "user", "parts": [{"text": TEXT}]}]  # untagged: one plain part
    assert kw["config"]["response_modalities"] == ["AUDIO"]
    assert kw["config"]["speech_config"] == {
        "language_code": "bn-BD",
        "voice_config": {"voice": "Kore"},
    }
    assert result.format == "wav" and result.sample_rate == 24000
    assert result.ttfb_ms is None and result.total_ms > 0
    assert result.request_id == "resp-1" and result.billed_chars == len(TEXT)
    with wave.open(io.BytesIO(result.audio)) as w:
        assert w.getnframes() == 12000


def test_headerless_pcm_is_wrapped_as_wav() -> None:
    with wave.open(io.BytesIO(to_wav(PCM, 24000))) as w:
        assert (w.getframerate(), w.getnchannels(), w.getnframes()) == (24000, 1, 12000)


C2PA = (
    b"C2PA" + (9).to_bytes(4, "little") + b"jumb-C2PA" + b"\x00"
)  # content-credentials chunk: id, size 9, data, pad


@pytest.mark.parametrize("declared", [len(PCM), 0, 0xFFFFFFFF])  # exact length, or a streamed placeholder
def test_trailing_c2pa_chunk_is_not_audio(declared: int) -> None:
    header = _wav(b"")[:36] + b"data" + declared.to_bytes(4, "little")
    with wave.open(io.BytesIO(to_wav(header + PCM + C2PA, 24000))) as w:
        assert w.getnframes() == 12000  # the metadata would otherwise play as a burst of static


def test_stream_ttfb_is_first_chunk(config_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def chunks(_kw):
        yield _resp(_wav(PCM[:8000]))
        time.sleep(0.05)
        yield _resp(None)
        yield _resp(PCM[8000:])

    p = _provider(GeminiStream, config_path, chunks, monkeypatch)
    result = p.synthesize(TEXT)
    assert p.mode == "stream" and 0 <= result.ttfb_ms <= result.total_ms
    assert result.total_ms - result.ttfb_ms >= 50
    with wave.open(io.BytesIO(result.audio)) as w:
        assert w.getnframes() == 12000


def test_rate_limit_is_not_retried(config_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def behaviour(_kw):
        raise errors.ClientError(429, {"error": {"status": "RESOURCE_EXHAUSTED"}})

    p = _provider(GeminiBatch, config_path, behaviour, monkeypatch)
    with pytest.raises(ProviderError) as exc:
        p.synthesize(TEXT)
    assert exc.value.status == 429 and len(p._client.models.calls) == 1


def test_client_error_is_not_retried(config_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def behaviour(_kw):
        raise errors.ClientError(403, {"error": {"status": "PERMISSION_DENIED"}})

    p = _provider(GeminiBatch, config_path, behaviour, monkeypatch)
    with pytest.raises(ProviderError) as exc:
        p.synthesize(TEXT)
    assert len(p._client.models.calls) == 1
    assert exc.value.status == 403 and str(exc.value) == "PERMISSION_DENIED"


def test_empty_audio_fails(config_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = _provider(GeminiBatch, config_path, lambda kw: _resp(None), monkeypatch)
    with pytest.raises(ProviderError, match="empty_audio"):
        p.synthesize(TEXT)


def test_supports_respects_max_chars(config_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p: GeminiProvider = _provider(GeminiBatch, config_path, lambda kw: _resp(_wav()), monkeypatch)
    assert p.supports(_item("ক" * 20)) and not p.supports(_item("ক" * 21))


def test_parse_output_format() -> None:
    assert parse_output_format("wav_24000") == ("wav", 24000)
    with pytest.raises(ConfigError):
        parse_output_format("mp3_24000")


# --- styles: build_parts ------------------------------------------------------------------------------------

STYLES = ("calm", "smug and proud", "soft and gentle")


def test_baseline_sends_the_text_unchanged_even_with_brackets() -> None:
    assert build_parts(TEXT) == [{"text": TEXT}]
    assert build_parts("[laugh] [বিজ্ঞপ্তি] আগামীকাল ক্লাস বন্ধ।") == [
        {"text": "[laugh] [বিজ্ঞপ্তি] আগামীকাল ক্লাস বন্ধ।"}  # no styles configured: nothing is cut out
    ]


def test_marker_becomes_speech_metadata_for_the_text_after_it() -> None:
    assert build_parts("[calm] এক। দুই।", STYLES) == [
        {"text": "এক। দুই।", "speech_metadata": {"style": "calm"}},
    ]


def test_a_style_lasts_until_the_next_marker() -> None:
    text = "[calm] এক। দুই। [smug and proud] তিন। চার।"
    assert build_parts(text, STYLES) == [
        {"text": "এক। দুই।", "speech_metadata": {"style": "calm"}},
        {"text": "তিন। চার।", "speech_metadata": {"style": "smug and proud"}},
    ]
    # the SDK accepts the shape
    assert types.Part(**build_parts(text, STYLES)[0]).speech_metadata.style == "calm"


def test_text_before_the_first_marker_has_no_style() -> None:
    assert build_parts("এক। [calm] দুই।", STYLES) == [
        {"text": "এক।"},
        {"text": "দুই।", "speech_metadata": {"style": "calm"}},
    ]


def test_a_marker_counts_anywhere_not_only_at_a_sentence_start() -> None:
    assert build_parts('মা বললেন, [soft and gentle] "সাবধানে যেও।"', STYLES) == [
        {"text": "মা বললেন,"},
        {"text": '"সাবধানে যেও।"', "speech_metadata": {"style": "soft and gentle"}},
    ]


def test_the_same_style_twice_is_two_parts() -> None:
    assert build_parts("[calm] এক। [calm] দুই।", STYLES) == [
        {"text": "এক।", "speech_metadata": {"style": "calm"}},
        {"text": "দুই।", "speech_metadata": {"style": "calm"}},
    ]


def test_only_exact_style_values_are_markers() -> None:
    text = "[বিজ্ঞপ্তি] [excited] [soft] ক্লাস বন্ধ।"
    assert build_parts(text, STYLES) == [{"text": text}]  # nothing matches, so nothing is cut out


def test_a_lone_marker_has_nothing_to_style() -> None:
    assert build_parts("[calm]", STYLES) == [{"text": "[calm]"}]


def test_inline_tags_stay_in_the_text() -> None:
    assert build_parts("[calm] আমি পেরেছি। <laugh>", STYLES) == [
        {"text": "আমি পেরেছি। <laugh>", "speech_metadata": {"style": "calm"}},
    ]


def test_missing_map_entry_leaves_no_style_or_text() -> None:
    from runner.emotion import style_values, translate_tags

    tag_map = {"calm": {"tag_type": "style", "value": "calm"}}  # "sigh" and "whisper" have no entry
    sent = translate_tags("[calm] এক। [sigh] দুই। [whisper] তিন।", tag_map)

    assert sent == "[calm] এক। দুই। তিন।"
    assert build_parts(sent, style_values(tag_map)) == [
        {"text": "এক। দুই। তিন।", "speech_metadata": {"style": "calm"}}  # the gaps neither split nor style
    ]


# --- styles: the request ------------------------------------------------------------------------------------


@pytest.mark.parametrize("cls", [GeminiBatch, GeminiStream])
def test_styles_from_config_reach_the_request(
    cls, config_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "google.genai.Client", lambda **_: SimpleNamespace(models=FakeModels(lambda _kw: None))
    )
    mode = "stream" if cls is GeminiStream else "batch"
    config = replace(load_provider_config(config_path, "gemini", mode), emotive_styles=STYLES)
    p = cls(config)
    p._client.models.behaviour = lambda _kw: _resp(_wav()) if cls is GeminiBatch else iter([_resp(_wav())])

    text = "[smug and proud] আমি পেরেছি। [calm] ঠিক আছে।"
    result = p.synthesize(text)

    kw = p._client.models.calls[0]
    assert kw["contents"][0]["parts"] == [
        {"text": "আমি পেরেছি।", "speech_metadata": {"style": "smug and proud"}},
        {"text": "ঠিক আছে।", "speech_metadata": {"style": "calm"}},
    ]
    assert kw["config"]["speech_config"]["voice_config"] == {
        "voice": "Kore"
    }  # a style does not change the voice
    assert result.billed_chars == len(text)  # billed on the text as given, markers included
