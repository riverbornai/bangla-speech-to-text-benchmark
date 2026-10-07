from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from runner.config import ConfigError
from runner.dataset import DatasetError, DatasetItem, load_dataset
from runner.emotion import load_tag_map, style_values, tag_map_path, translate_tags
from runner.main import emotive_items

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"

EL = {"laugh": "[laughs]", "short_pause": "[short pause]", "sarcastic": "[sarcastically]"}
CARTESIA = {"happy": '<emotion value="happy"/>', "short_pause": '<break time="300ms"/>'}
GEMINI = {
    "calm": {"tag_type": "style", "value": "calm"},
    "smug_proud": {"tag_type": "style", "value": "smug and proud"},
    "laugh": {"tag_type": "tag", "value": "<laugh>"},
}


def test_value_replaces_the_bracketed_key_verbatim() -> None:
    assert translate_tags("[laugh] হাসির কথা।", EL) == "[laughs] হাসির কথা।"
    assert translate_tags("[short_pause] এক।", EL) == "[short pause] এক।"
    assert translate_tags("[happy] আজ ভালো দিন।", CARTESIA) == '<emotion value="happy"/> আজ ভালো দিন।'


def test_every_tag_is_replaced_wherever_it_sits() -> None:
    text = "[sarcastic] এক। দুই, [laugh] তিন। চার। [laugh]"
    assert translate_tags(text, EL) == "[sarcastically] এক। দুই, [laughs] তিন। চার। [laughs]"


def test_text_without_tags_is_unchanged() -> None:
    assert translate_tags(" স্কুলটি এখান থেকে ৫ কি.মি. দূরে। ", EL) == " স্কুলটি এখান থেকে ৫ কি.মি. দূরে। "


def test_key_with_no_entry_becomes_empty_string() -> None:
    assert translate_tags("[sigh] আচ্ছা, ঠিক আছে।", EL) == "আচ্ছা, ঠিক আছে।"  # start
    assert translate_tags("ঘুম থেকে উঠে [yawn] আমি চা খাই।", EL) == "ঘুম থেকে উঠে আমি চা খাই।"  # middle
    assert translate_tags("শহরের যানজট বাড়ছে। [sigh]", EL) == "শহরের যানজট বাড়ছে।"  # end
    assert translate_tags("[laugh] [sigh] এক।", EL) == "[laughs] এক।"
    assert translate_tags("[sigh] এক।", {}) == "এক।"  # a provider with an empty map keeps only the text


def test_bangla_brackets_stay_as_content() -> None:
    assert translate_tags("[laugh] [বিজ্ঞপ্তি] ক্লাস বন্ধ।", EL) == "[laughs] [বিজ্ঞপ্তি] ক্লাস বন্ধ।"


def test_gemini_style_is_marked_and_tag_is_inline() -> None:
    assert (
        translate_tags("[smug_proud] আমি পেরেছি। [laugh]", GEMINI) == "[smug and proud] আমি পেরেছি। <laugh>"
    )
    assert style_values(GEMINI) == ("calm", "smug and proud")
    assert style_values(EL) == ()  # only Gemini has payload styles


def test_load_tag_map_validates(tmp_path: Path) -> None:
    good = tmp_path / "x.json"
    good.write_text(json.dumps({**EL, **GEMINI}), encoding="utf-8")
    assert load_tag_map(good)["laugh"] == {"tag_type": "tag", "value": "<laugh>"}
    with pytest.raises(ConfigError, match="not found"):
        load_tag_map(tmp_path / "nope.json")
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"calm": {"tag_type": "weird", "value": "calm"}}), encoding="utf-8")
    with pytest.raises(ConfigError, match="'calm' must be"):
        load_tag_map(bad)


def test_tag_map_lives_next_to_providers_yaml() -> None:
    assert tag_map_path("config/providers.yaml", "elevenlabs") == Path("config/elevenlabs.json")


def _dataset() -> Path:
    found = next(ROOT.glob("bangla_tts_benchmark_dataset_v*.xlsx"), None)
    if found is None:
        pytest.skip("dataset workbook not in the repo")
    return found


# Dataset keys each provider's file deliberately has no entry for (they are sent as an empty string).
# If a map gains or loses an entry, this list must change with it, so a gap is never silent.
MISSING = {
    "elevenlabs": {"higher_pitch", "lower_pitch"},
    "gemini": set(),
    "soniox": {"smug_proud"},
    "cartesia": {
        "sigh", "yawn", "chuckle", "breath_exhale", "whisper", "lower_pitch",
        "gasp", "clear_throat", "cry_sob", "cough", "higher_pitch", "giggle",
    },
}  # fmt: skip
TAG = re.compile(r"\[([A-Za-z_]+)\]")


@pytest.mark.parametrize("provider", sorted(MISSING))
def test_real_maps_load_and_report_exactly_the_missing_dataset_keys(provider: str) -> None:
    tag_map = load_tag_map(CONFIG / f"{provider}.json")
    keys = {k for it in load_dataset(_dataset()) for k in TAG.findall(it.text_emotive or "")}
    assert keys - set(tag_map) == MISSING[provider]


@pytest.mark.parametrize("provider", sorted(MISSING))
def test_dataset_tag_missing_from_the_map_is_removed_cleanly(provider: str) -> None:
    """A tag the provider has no entry for leaves no brackets, no stray spaces and no empty text behind."""
    tag_map = load_tag_map(CONFIG / f"{provider}.json")
    checked = 0
    for item in load_dataset(_dataset()):
        gone = {k for k in TAG.findall(item.text_emotive or "") if k not in tag_map}
        if not gone:
            continue
        checked += 1
        sent = translate_tags(item.text_emotive or "", tag_map)
        assert not any(f"[{k}]" in sent for k in gone), item.item_id
        assert sent and sent == sent.strip() and "  " not in sent, (item.item_id, sent)
    assert (checked > 0) == bool(MISSING[provider])  # rows with gaps exist exactly when the map has gaps


def test_missing_tag_removal_keeps_the_rest_of_the_text_byte_for_byte() -> None:
    text = "[excited] অভিনন্দন! 🎉 তুমি পাশ করেছ 😊 [giggle]"  # real BN-EDG-003: tag at the end, after emoji
    assert translate_tags(text, {"excited": "[excited]"}) == "[excited] অভিনন্দন! 🎉 তুমি পাশ করেছ 😊"
    assert translate_tags("[sigh] [yawn] এক।", {}) == "এক।"  # adjacent missing tags
    assert translate_tags("এক। [sigh]\nদুই।", {}) == "এক। দুই।"  # the whitespace after a removed tag is dropped
    assert translate_tags("[laugh]", {}) == ""  # nothing left; emotive_items must not send an empty request


def test_item_left_empty_by_missing_tags_is_rejected_before_any_request() -> None:
    only_tag = DatasetItem("BN-X-001", "x", None, (), "plain", None, None, 1, text_emotive="[sigh]")
    with pytest.raises(DatasetError, match="BN-X-001.*nothing left"):
        emotive_items([only_tag], {})


def test_real_elevenlabs_output_has_no_raw_keys_left() -> None:
    tag_map = load_tag_map(CONFIG / "elevenlabs.json")
    for item in load_dataset(_dataset()):
        sent = translate_tags(item.text_emotive or "", tag_map)
        assert not re.search(r"\[[A-Za-z]+_[A-Za-z_]+\]", sent), item.item_id  # e.g. [scared_fearful]
        assert sent == sent.strip() and sent, item.item_id
