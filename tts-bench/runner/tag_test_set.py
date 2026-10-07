"""Tag each sentence of the STT test set with an emotion and write per-provider TTS text to Excel.

For every row of data/test-set.csv the sentence gets one common tag (happy, sad, laugh, ...),
detected from Bangla keywords and punctuation (see RULES). Each provider column holds the
sentence with that provider's clean value in front, the same value as in emotion_map.json:

    common tag | Eleven Labs   | Gemini 3.8 Flash | Cartesia Sonic 3 | Soniox
    sad        | [sad] কষ্ট... | [sad] কষ্ট...     | [sad] কষ্ট...     | [sad] কষ্ট...
    warm       | [warmly] ...  | [warm] ...       | [affectionate] ...| [warm] ...
    neutral    | হ্যাঁ।         | হ্যাঁ।            | হ্যাঁ।            | হ্যাঁ।

Rules:
- If the CSV has an "emotion" column, a non-empty value there wins over detection
  (it must be a "Common Tag" from the sheet). Use it to fix wrong guesses by hand.
- A sentence with no keyword match is "neutral" and keeps its plain text in every column.
- If a provider has no value for the emotion ("—" in the sheet), that cell gets plain text.
- Values are cleaned exactly like emotion_map.json (see runner/style_map.py): no XML, no
  style: "...", no "≈"; '<volume ratio="0.5"/>' becomes [0.5].

Usage (from tts-bench/):
    python -m runner.tag_test_set
    python -m runner.tag_test_set --csv ../data/test-set.csv --tags local/emotion_map.xlsx \\
        --out local/test_set_tagged.xlsx
Needs no extra packages.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path
from xml.sax.saxutils import escape

from runner.style_map import PROVIDERS, StyleMapError, load_style_map, tag_key

# First column found is the sentence. "text" = TTS dataset, the other = STT test set.
TEXT_COLUMNS = ("text", "ground_truth_transcription_bn")
NEUTRAL = "neutral"

# Output column header for each provider key. Order here = column order in the Excel.
# Only providers also enabled in style_map.PROVIDERS are written.
OUTPUT_COLUMNS = {
    "elevenlabs_v3": "Eleven Labs",
    "gemini_3.8_flash_tts": "Gemini 3.8 Flash",
    "cartesia_sonic-3": "Cartesia Sonic 3",
    "soniox_tts_v2": "Soniox",
    "chirp_3_hd": "Chirp 3 HD",
    "sarvam_bulbul": "Sarvam (Bulbul)",
}

# Rules: common tag -> keywords, checked top to bottom; the first match wins.
# A keyword matches a whole word; end it with "*" to also match longer words ("খুশি*" matches "খুশিতে").
# Keywords starting with "re:" are regular expressions. Tags must be "Common Tag" values from the sheet.
RULES: list[tuple[str, tuple[str, ...]]] = [
    ("laugh", ("হা হা", "হাহা", "হি হি", "হিহি", "হো হো")),
    ("angry", ("রাগ*", "ক্ষোভ*", "ক্ষুব্ধ", "নিন্দা*", "বেয়াদব*", "অসভ্য*")),
    ("sad", ("দুঃখ", "কষ্ট*", "শোক*", "মৃত্যু*", "কান্না*", "কাঁদ*", "হায়", "দুর্ভাগ্য*", "বেচারা", "অসহায়*")),
    ("scared / fearful", ("ভয়*", "ভূত*", "আতঙ্ক*", "বাঁচাও", "সর্বনাশ")),
    ("annoyed", ("উফ*", "ধুর", "না না", "আগেই বলেছিলাম")),
    ("hesitant", (r"re:\.\.\.|…",)),
    ("surprised", ("আরে", "অবাক*", "বিস্ময়*", "তাই নাকি", "বাপরে", "আনএক্সপেক্টেড", "unexpected",
                   r"re:কী [^।?]*!")),
    ("excited", ("অভিনন্দন*", "চমৎকার", "দারুণ", "অসাধারণ", "দুর্দান্ত", "জিতে*", "চ্যাম্পিয়ন*")),
    ("happy", ("আনন্দ*", "খুশি*", "মজা*")),
    ("smug / proud", ("গর্ব*",)),
    ("sincere / empathetic", ("ক্ষমা*", "দুঃখিত", "শান্তি কামনা", "sorry")),
    ("warm", ("ধন্যবাদ", "শুভেচ্ছা", "শুভ", "প্রিয়", "সাবধানে", "ভালোবাসা*", "thank you", "স্বাগত*")),
    ("serious", ("warning", "সতর্ক*", "জরুরি")),
    ("curious", (r"re:\?",)),
]  # fmt: skip

_LETTER = r"[\w\u0980-\u09FF\u200c\u200d]"


def _pattern(words: tuple[str, ...]) -> re.Pattern[str]:
    parts = []
    for w in words:
        if w.startswith("re:"):
            parts.append(f"(?:{w[3:]})")
        elif w.endswith("*"):
            parts.append(f"(?<!{_LETTER}){re.escape(w[:-1])}")
        else:
            parts.append(f"(?<!{_LETTER}){re.escape(w)}(?!{_LETTER})")
    return re.compile("|".join(parts), re.IGNORECASE)


_PATTERNS = [(tag, _pattern(words)) for tag, words in RULES]


def detect_emotion(text: str) -> str:
    for tag, pattern in _PATTERNS:
        if pattern.search(text):
            return tag
    return NEUTRAL


def load_provider_tags(tags_path: Path) -> dict[str, dict[str, str]]:
    """{common tag key: {provider key: clean value}}, the same values as emotion_map.json.

    e.g. {"whisper": {"cartesia_sonic-3": "0.5", ...}, "scared_fearful": {...}}
    """
    wanted = [k for k in OUTPUT_COLUMNS if k in PROVIDERS]
    return load_style_map(
        tags_path, key_column="Common Tag", ignore_columns=["Category"], only_providers=wanted
    )


def apply_tag(value: str | None, text: str) -> str:
    """'[value] text', or the plain text when the provider has no value for this emotion."""
    return f"[{value}] {text}" if value else text


def build_rows(csv_path: Path, tags: dict[str, dict[str, str]]) -> tuple[list[str], list[list[str]]]:
    providers = [k for k in OUTPUT_COLUMNS if k in PROVIDERS]
    header = ["common tag", *(OUTPUT_COLUMNS[k] for k in providers)]
    rows: list[list[str]] = []
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        text_col = next((c for c in TEXT_COLUMNS if c in (reader.fieldnames or [])), None)
        if text_col is None:
            raise StyleMapError(f"{csv_path}: none of {TEXT_COLUMNS} found (have {reader.fieldnames})")
        for line_no, rec in enumerate(reader, start=2):
            text = rec.get(text_col) or ""  # kept exactly as written: never strip or normalize TTS input
            if not text.strip():
                continue
            tag = tag_key((rec.get("emotion") or "").strip() or detect_emotion(text))
            if tag != NEUTRAL and tag not in tags:
                raise StyleMapError(
                    f"{csv_path}: row {line_no}: emotion {tag!r} is not a Common Tag in the sheet"
                )
            per_provider = tags.get(tag, {})
            rows.append([tag, *(apply_tag(per_provider.get(k), text) for k in providers)])
    return header, rows


# --- minimal .xlsx writer (stdlib only) ---
def _col(n: int) -> str:
    s = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def write_xlsx(path: Path, header: list[str], rows: list[list[str]], sheet: str = "Tagged") -> None:
    def row_xml(r: int, values: list[str], style: int = 0) -> str:
        cells = "".join(
            f'<c r="{_col(c)}{r}" t="inlineStr" s="{style}">'
            f'<is><t xml:space="preserve">{escape(v)}</t></is></c>'
            for c, v in enumerate(values)
        )
        return f'<row r="{r}">{cells}</row>'

    widths = "".join(
        f'<col min="{i + 1}" max="{i + 1}" width="{14 if i == 0 else 60}" customWidth="1"/>'
        for i in range(len(header))
    )
    body = row_xml(1, header, 1) + "".join(row_xml(i + 2, r) for i, r in enumerate(rows))
    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" state="frozen"/>'
        "</sheetView></sheetViews>"
        f"<cols>{widths}</cols><sheetData>{body}</sheetData>"
        f'<autoFilter ref="A1:{_col(len(header) - 1)}{len(rows) + 1}"/></worksheet>'
    )
    files = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" '
            'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/styles.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            "</Types>"
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="xl/workbook.xml"/></Relationships>'
        ),
        "xl/workbook.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'<sheets><sheet name="{escape(sheet)}" sheetId="1" r:id="rId1"/></sheets>'
            f'<definedNames><definedName name="_xlnm._FilterDatabase" localSheetId="0" hidden="1">'
            f"'{escape(sheet)}'!$A$1:${_col(len(header) - 1)}${len(rows) + 1}</definedName></definedNames>"
            "</workbook>"
        ),
        "xl/_rels/workbook.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            'Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
            'Target="styles.xml"/></Relationships>'
        ),
        "xl/styles.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
            '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
            '<fills count="2"><fill><patternFill patternType="none"/></fill>'
            '<fill><patternFill patternType="gray125"/></fill></fills>'
            '<borders count="1"><border/></borders>'
            '<cellStyleXfs count="1"><xf/></cellStyleXfs>'
            '<cellXfs count="2"><xf fontId="0" xfId="0"/><xf fontId="1" xfId="0" applyFont="1"/></cellXfs>'
            '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
            "</styleSheet>"
        ),
        "xl/worksheets/sheet1.xml": sheet_xml,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)


def main(argv: list[str] | None = None) -> int:
    here = Path(__file__).resolve().parent.parent  # tts-bench/
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    data = here.parent / "data"
    default_csv = next(
        (f for f in (data / "test-set.csv", data / "test_set.csv") if f.exists()), data / "test-set.csv"
    )
    p.add_argument("--csv", type=Path, default=default_csv)
    p.add_argument("--tags", type=Path, default=here / "local" / "emotion_map.xlsx", help="tag sheet")
    p.add_argument("--out", type=Path, default=here / "local" / "test_set_tagged.xlsx")
    args = p.parse_args(argv)

    try:
        tags = load_provider_tags(args.tags)
        header, rows = build_rows(args.csv, tags)
    except (StyleMapError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    write_xlsx(args.out, header, rows)

    counts = Counter(r[0] for r in rows)
    print(f"wrote {len(rows)} rows to {args.out}", file=sys.stderr)
    for tag, n in counts.most_common():
        print(f"  {tag:<18} {n}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
