from __future__ import annotations

import json
from pathlib import Path

import pytest
from openpyxl import Workbook

from runner.style_map import StyleMapError, bare_tag, load_style_map, main, provider_key

HEADER = [
    "Category",
    "Common Tag",
    # "Chirp 3 HD",
    "ElevenLabs v3",
    "Gemini 3.8 Flash TTS",
    "Cartesia Sonic-3",
    # "Sarvam (Bulbul)",
    "Soniox TTS v2",
]  # fmt: skip
HAPPY = [
    "Emotion",
    "happy",
    # "≈ punctuation (!)",
    "[happy]",
    'style: "happy"',
    '<emotion value="happy"/>',
    # "≈ wording / temperature↑",
    "[happy]",
]  # fmt: skip


def _xlsx(path: Path, rows: list[list], title: str = "Sheet1") -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = title
    for r in rows:
        ws.append(r)
    wb.save(path)
    return path


def test_tag_sheet_to_clean_nested_dict(tmp_path: Path) -> None:
    path = _xlsx(tmp_path / "m.xlsx", [HEADER, HAPPY, [None] * len(HEADER)])
    got = load_style_map(path, key_column="Common Tag", ignore_columns=["Category"])
    assert got == {
        "happy": {
            # "chirp_3_hd": "≈ punctuation (!)",
            "elevenlabs_v3": "happy",
            "gemini_3.8_flash_tts": "happy",
            "cartesia_sonic-3": "happy",
            # "sarvam_bulbul": "≈ wording / temperature↑",
            "soniox_tts_v2": "happy",
        }
    }


def test_no_approx_drops_approximate_entries(tmp_path: Path) -> None:
    path = _xlsx(tmp_path / "m.xlsx", [HEADER, HAPPY])
    got = load_style_map(path, key_column="Common Tag", ignore_columns=["Category"], keep_approx=False)
    assert set(got["happy"]) == {"elevenlabs_v3", "gemini_3.8_flash_tts", "cartesia_sonic-3", "soniox_tts_v2"}


def test_raw_keeps_headers_and_cells(tmp_path: Path) -> None:
    path = _xlsx(tmp_path / "m.xlsx", [HEADER, HAPPY])
    got = load_style_map(path, key_column="Common Tag", ignore_columns=["Category"], raw=True)
    assert got["happy"]["ElevenLabs v3"] == "[happy]"
    # assert got["happy"]["Chirp 3 HD"] == "≈ punctuation (!)"


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        ("[sarcastically]", "sarcastically"),
        ("[clears throat]", "clears throat"),
        ('style: "smug and proud"', "smug and proud"),
        ('<emotion value="joking/comedic"/>', "joking/comedic"),
        ("<laugh>", "laugh"),
        ("<short pause>", "short pause"),
        ("<throat-clearing>", "throat-clearing"),
        ('<break time="300ms"/>', "300ms"),
        ('<volume ratio="2.0"/>', "2.0"),
        ('≈ <volume ratio="0.5"/>', "0.5"),  # approx: "≈" removed, then cleaned
        ('<prosody rate="slow"> / speaking_rate', '<prosody rate="slow"> / speaking_rate'),  # kept
        ("pace: 0.8", "pace: 0.8"),
        ("≈ [laughter]", "laughter"),
    ],
)
def test_bare_tag(cell: str, expected: str | None) -> None:
    assert bare_tag(cell) == expected


def test_bare_tag_drops_approx_when_asked() -> None:
    assert bare_tag("≈ [laughter]", keep_approx=False) is None


def test_provider_key() -> None:
    assert provider_key("Gemini 3.8 Flash TTS") == "gemini_3.8_flash_tts"
    assert provider_key("Cartesia Sonic-3") == "cartesia_sonic-3"
    # assert provider_key("Sarvam (Bulbul)") == "sarvam_bulbul"
    assert provider_key("OpenAI gpt-4o-mini-tts") == "openai_gpt-4o-mini-tts"


def test_dash_means_missing(tmp_path: Path) -> None:
    path = _xlsx(tmp_path / "m.xlsx", [["tag", "ElevenLabs v3", "Chirp 3 HD"], ["sigh", "[sighs]", "—"]])
    assert load_style_map(path) == {"sigh": {"elevenlabs_v3": "sighs"}}


def test_duplicate_key_fails(tmp_path: Path) -> None:
    path = _xlsx(tmp_path / "m.xlsx", [["tag", "gemini"], ["happy", "a"], ["happy", "b"]])
    with pytest.raises(StyleMapError, match="duplicate key"):
        load_style_map(path)


def test_missing_sheet_and_columns_fail(tmp_path: Path) -> None:
    path = _xlsx(tmp_path / "m.xlsx", [["tag", "gemini"]])
    with pytest.raises(StyleMapError, match="not found"):
        load_style_map(path, sheet="Nope")
    with pytest.raises(StyleMapError, match="key column"):
        load_style_map(path, key_column="Common Tag")
    with pytest.raises(StyleMapError, match="ignore column"):
        load_style_map(path, ignore_columns=["Category"])


def test_cli_writes_utf8_json(tmp_path: Path) -> None:
    path = _xlsx(tmp_path / "m.xlsx", [["tag", "Gemini 3.8 Flash TTS"], ["happy", "উৎফুল্ল"]])
    out = tmp_path / "m.json"
    assert main([str(path), "--out", str(out)]) == 0
    assert "উৎফুল্ল" in out.read_text(encoding="utf-8")  # not \u-escaped
    assert json.loads(out.read_text(encoding="utf-8")) == {"happy": {"gemini_3.8_flash_tts": "উৎফুল্ল"}}


def test_cli_leaves_out_commented_providers(tmp_path: Path) -> None:
    full_header = ["Common Tag", "Chirp 3 HD", "ElevenLabs v3", "Sarvam (Bulbul)"]
    full_row = ["happy", "≈ punctuation (!)", "[happy]", "≈ wording"]
    path = _xlsx(tmp_path / "m.xlsx", [["Category", *full_header], ["Emotion", *full_row]])
    out = tmp_path / "m.json"
    args = [str(path), "--key-column", "Common Tag", "--ignore-column", "Category", "--out", str(out)]
    assert main(args) == 0
    happy = json.loads(out.read_text(encoding="utf-8"))["happy"]
    assert "chirp_3_hd" not in happy and "sarvam_bulbul" not in happy
    assert main([*args, "--all-providers"]) == 0
    happy = json.loads(out.read_text(encoding="utf-8"))["happy"]
    assert "chirp_3_hd" in happy and "sarvam_bulbul" in happy


def test_tag_keys_become_snake_case(tmp_path: Path) -> None:
    path = _xlsx(
        tmp_path / "m.xlsx",
        [["tag", "Cartesia Sonic-3"], ["breath / exhale", "[x]"], ["short pause", '<break time="300ms"/>']],
    )
    assert load_style_map(path) == {
        "breath_exhale": {"cartesia_sonic-3": "x"},
        "short_pause": {"cartesia_sonic-3": "300ms"},
    }
    assert "breath / exhale" in load_style_map(path, raw=True)  # --raw keeps the sheet's names
