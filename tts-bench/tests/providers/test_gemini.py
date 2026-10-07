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
from runner.providers import base
from runner.providers.base import ProviderError
from runner.providers.gemini import GeminiBatch, GeminiProvider, GeminiStream, parse_output_format
from runner.providers.gemini._common import to_wav
from runner.providers.gemini.styles import build_parts

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


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(base, "sleep", lambda _: None)


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
    assert result.request_id == "resp-1" and result.billed_chars == len(TEXT) and result.attempts == 1
    with wave.open(io.BytesIO(result.audio)) as w:
        assert w.getnframes() == 12000


def test_headerless_pcm_is_wrapped_as_wav() -> None:
    with wave.open(io.BytesIO(to_wav(PCM, 24000))) as w:
        assert (w.getframerate(), w.getnchannels(), w.getnframes()) == (24000, 1, 12000)


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


def test_retries_on_429_then_succeeds(config_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    outcomes = [errors.ClientError(429, {"error": {"status": "RESOURCE_EXHAUSTED"}}), _resp(_wav())]

    def behaviour(_kw):
        o = outcomes.pop(0)
        if isinstance(o, Exception):
            raise o
        return o

    p = _provider(GeminiBatch, config_path, behaviour, monkeypatch)
    assert p.synthesize(TEXT).attempts == 2


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


def test_style_tags_become_speech_metadata() -> None:
    text = "[laugh] হাসির কথা। সাধারণ বাক্য। [whisper] ফিসফিস। আবার সাধারণ।"
    assert build_parts(text) == [
        {"text": "হাসির কথা। সাধারণ বাক্য।", "speech_metadata": {"style": "laugh"}},
        {"text": "ফিসফিস। আবার সাধারণ।", "speech_metadata": {"style": "whisper"}},
    ]
    # the SDK accepts the shape
    assert types.Part(**build_parts(text)[0]).speech_metadata.style == "laugh"


def test_untagged_prefix_and_bangla_brackets_stay_plain() -> None:
    assert build_parts("প্রথম বাক্য। [cheerful] দ্বিতীয়।") == [
        {"text": "প্রথম বাক্য।"},
        {"text": "দ্বিতীয়।", "speech_metadata": {"style": "cheerful"}},
    ]
    assert build_parts("[বিজ্ঞপ্তি] আগামীকাল ক্লাস বন্ধ থাকবে।") == [{"text": "[বিজ্ঞপ্তি] আগামীকাল ক্লাস বন্ধ থাকবে।"}]
    assert build_parts("মাঝে [laugh] আছে") == [{"text": "মাঝে [laugh] আছে"}]  # not at a sentence start
    assert build_parts("[laugh]") == [{"text": "[laugh]"}]


def test_only_single_english_word_tags_are_styles() -> None:
    assert build_parts("[excited, fast-paced] দ্রুত।") == [{"text": "[excited, fast-paced] দ্রুত।"}]
    assert build_parts("[two words] দ্রুত।") == [{"text": "[two words] দ্রুত।"}]


def test_tag_needs_whitespace_after_sentence_end_or_start_of_text() -> None:
    assert build_parts("প্রথম।\n[whisper] ফিসফিস।") == [
        {"text": "প্রথম।"},
        {"text": "ফিসফিস।", "speech_metadata": {"style": "whisper"}},
    ]
    assert build_parts("প্রথম।[whisper] ফিসফিস।") == [
        {"text": "প্রথম।[whisper] ফিসফিস।"}
    ]  # no space: not a tag


STYLED = "[laugh] হাসির কথা। [whisper] ফিসফিস।"


@pytest.mark.parametrize("cls", [GeminiBatch, GeminiStream])
def test_styled_text_is_sent_as_styled_parts(cls, config_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = _provider(
        cls,
        config_path,
        lambda _kw: _resp(_wav()) if cls is GeminiBatch else iter([_resp(_wav())]),
        monkeypatch,
    )
    result = p.synthesize(STYLED)

    kw = p._client.models.calls[0]
    assert kw["contents"] == [
        {
            "role": "user",
            "parts": [
                {"text": "হাসির কথা।", "speech_metadata": {"style": "laugh"}},
                {"text": "ফিসফিস।", "speech_metadata": {"style": "whisper"}},
            ],
        }
    ]
    # style does not change the voice
    assert kw["config"]["speech_config"]["voice_config"] == {"voice": "Kore"}
    assert result.billed_chars == len(STYLED)  # billed on the original text, tags included


def test_styled_request_is_accepted_by_the_sdk_types() -> None:
    contents = types.Content(role="user", parts=[types.Part(**p) for p in build_parts(STYLED)])
    assert [p.speech_metadata.style for p in contents.parts] == ["laugh", "whisper"]


def test_style_covers_every_sentence_until_the_next_tag() -> None:
    text = "এক। [laugh] দুই। তিন। [whisper] চার। পাঁচ।"
    assert build_parts(text) == [
        {"text": "এক।"},
        {"text": "দুই। তিন।", "speech_metadata": {"style": "laugh"}},
        {"text": "চার। পাঁচ।", "speech_metadata": {"style": "whisper"}},
    ]


def test_tags_after_any_sentence_terminator() -> None:
    assert build_parts("এক? [shout] দুই! [sad] তিন… [calm] চার.") == [
        {"text": "এক?"},
        {"text": "দুই!", "speech_metadata": {"style": "shout"}},
        {"text": "তিন…", "speech_metadata": {"style": "sad"}},
        {"text": "চার.", "speech_metadata": {"style": "calm"}},
    ]


def test_repeated_style_is_not_merged() -> None:
    assert build_parts("[laugh] এক। [laugh] দুই।") == [
        {"text": "এক।", "speech_metadata": {"style": "laugh"}},
        {"text": "দুই।", "speech_metadata": {"style": "laugh"}},
    ]


def test_multiple_untagged_sentences_stay_in_one_part() -> None:
    assert build_parts("এক। দুই। তিন।") == [{"text": "এক। দুই। তিন।"}]
    assert build_parts("এক। দুই। [whisper] তিন।") == [
        {"text": "এক। দুই।"},
        {"text": "তিন।", "speech_metadata": {"style": "whisper"}},
    ]


def test_inline_tag_in_a_later_sentence_is_not_a_style() -> None:
    text = "[laugh] এক। দুই [whisper] তিন। চার।"
    assert build_parts(text) == [{"text": "এক। দুই [whisper] তিন। চার।", "speech_metadata": {"style": "laugh"}}]


STYLES = ("smug and proud", "soft and gentle")


def test_emotive_markers_become_speech_metadata_wherever_they_sit() -> None:
    text = '[smug and proud] আমি পেরেছি। <laugh> মা বললেন, [soft and gentle] "সাবধানে যেও।"'
    assert build_parts(text, STYLES) == [
        {"text": "আমি পেরেছি। <laugh> মা বললেন,", "speech_metadata": {"style": "smug and proud"}},
        {"text": '"সাবধানে যেও।"', "speech_metadata": {"style": "soft and gentle"}},
    ]
    assert build_parts("মা বললেন, [soft and gentle] ধীরে।", STYLES) == [  # untagged text before a marker
        {"text": "মা বললেন,"},
        {"text": "ধীরে।", "speech_metadata": {"style": "soft and gentle"}},
    ]


def test_emotive_only_exact_style_values_are_markers() -> None:
    text = "[বিজ্ঞপ্তি] [excited] [soft] ক্লাস বন্ধ।"
    assert build_parts(text, STYLES) == [{"text": text}]  # no part is styled, text is sent as-is
    assert build_parts("[smug and proud]", STYLES) == [{"text": "[smug and proud]"}]  # nothing to style


def test_emotive_markers_ignore_the_sentence_start_rule_of_the_baseline() -> None:
    # Baseline needs a sentence start; the emotive markers come from our own map, so any position counts.
    assert build_parts("মাঝে [smug and proud] আছে", STYLES) == [
        {"text": "মাঝে"},
        {"text": "আছে", "speech_metadata": {"style": "smug and proud"}},
    ]
    assert build_parts("মাঝে [smug and proud] আছে") == [{"text": "মাঝে [smug and proud] আছে"}]  # baseline


@pytest.mark.parametrize("cls", [GeminiBatch, GeminiStream])
def test_emotive_styles_from_config_reach_the_request(
    cls, config_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "google.genai.Client", lambda **_: SimpleNamespace(models=FakeModels(lambda _kw: None))
    )
    config = replace(load_provider_config(config_path, "gemini", "batch"), emotive_styles=STYLES)
    p = cls(config)
    p._client.models.behaviour = lambda _kw: _resp(_wav()) if cls is GeminiBatch else iter([_resp(_wav())])

    p.synthesize("[smug and proud] আমি পেরেছি। <laugh>")

    parts = p._client.models.calls[0]["contents"][0]["parts"]
    assert parts == [{"text": "আমি পেরেছি। <laugh>", "speech_metadata": {"style": "smug and proud"}}]


def test_dataset_tag_missing_from_gemini_map_leaves_no_style_or_text() -> None:
    from runner.emotion import style_values, translate_tags

    tag_map = {"calm": {"tag_type": "style", "value": "calm"}}  # "sigh" and "whisper" have no entry
    sent = translate_tags("[calm] এক। [sigh] দুই। [whisper] তিন।", tag_map)

    assert sent == "[calm] এক। দুই। তিন।"
    assert build_parts(sent, style_values(tag_map)) == [
        {
            "text": "এক। দুই। তিন।",
            "speech_metadata": {"style": "calm"},
        }  # the gaps neither split nor add a style
    ]
