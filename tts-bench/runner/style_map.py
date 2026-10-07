"""Convert a tag sheet (rows = tags, columns = providers) into nested JSON.

Input workbook, first sheet unless --sheet is given:

    | Category | Common Tag | ElevenLabs v3 | Gemini 3.8 Flash TTS | Chirp 3 HD        |
    |----------|------------|---------------|----------------------|-------------------|
    | Emotion  | happy      | [happy]       | style: "happy"       | ≈ punctuation (!) |
    | Emotion  | sarcastic  | [sarcastically] | style: "sarcastic" | —                 |

Output (default, cleaned):

    {"happy":     {"elevenlabs_v3": "happy", "gemini_3.8_flash_tts": "happy"},
     "sarcastic": {"elevenlabs_v3": "sarcastically", "gemini_3.8_flash_tts": "sarcastic"}}

Cleaning rules (turn off with --raw):
- Provider headers become snake_case keys: "ElevenLabs v3" -> "elevenlabs_v3",
  "Sarvam (Bulbul)" -> "sarvam_bulbul".
- The bare tag is pulled out of its wrapper: "[happy]", 'style: "happy"',
  '<emotion value="happy"/>' and "<laugh>" all become the plain word.
  Values with any other shape (e.g. '<break time="300ms"/>', "pace: 0.8") are kept as written.
- Approximate entries starting with "≈" (workarounds, not real tags) are kept as written,
  e.g. "chirp_3_hd": "≈ punctuation (!)". Pass --no-approx to drop them.

Always: empty cells and dash placeholders ("—", "–", "-") are left out, so a provider
with no tag for a row does not appear under it.

Usage:
    python -m runner.style_map local/emotion_map.xlsx --key-column "Common Tag" \\
        --ignore-column Category --out local/emotion_map.json
    python -m runner.style_map mapping.xlsx --raw      # keep headers and cells as written
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


class StyleMapError(ValueError):
    pass


# Cells that mean "no value" in a hand-filled sheet.
_MISSING = {"", "—", "–", "-"}
_APPROX = "≈"

# Wrappers around a bare tag, tried in order; group 1 is the tag.
_TAG_PATTERNS = (
    re.compile(r"^\[([^\[\]]+)\]$"),  # [happy]
    re.compile(r'^style:\s*"([^"]+)"$'),  # style: "happy"
    re.compile(r'^<\s*emotion\s+value\s*=\s*"([^"]+)"\s*/?>$'),  # <emotion value="happy"/>
    re.compile(r'^<([^<>="/]+)>$'),  # <laugh>, <short pause>
)


def _cell(value: object) -> str:
    text = "" if value is None else str(value).strip()
    return "" if text in _MISSING else text


def provider_key(header: str) -> str:
    """'Gemini 3.8 Flash TTS' -> 'gemini_3.8_flash_tts'; 'Sarvam (Bulbul)' -> 'sarvam_bulbul'."""
    key = re.sub(r"[^\w.\-]+", "_", header.strip().lower())
    return key.strip("_")


def bare_tag(value: str, keep_approx: bool = True) -> str | None:
    """Pull the plain tag out of a provider-specific wrapper.

    Approximate entries ("≈ ...") are returned as written, or None when keep_approx is False.
    """
    if value.startswith(_APPROX):
        return value if keep_approx else None
    for pattern in _TAG_PATTERNS:
        m = pattern.match(value)
        if m:
            return m.group(1).strip()
    return value


# --- minimal .xlsx reader (stdlib only, so the utility needs no extra install) ---
_NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}


def _col_index(ref: str) -> int:
    """'C7' -> 2 (zero-based column)."""
    n = 0
    for ch in ref:
        if not ch.isalpha():
            break
        n = n * 26 + (ord(ch.upper()) - 64)
    return n - 1


def _read_xlsx(path: str | Path):
    """Return {sheet name: callable yielding rows as tuples of cell values}, in workbook order."""
    import xml.etree.ElementTree as ET
    import zipfile

    try:
        zf = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, FileNotFoundError, IsADirectoryError) as e:
        raise StyleMapError(f"{path}: not a readable .xlsx file ({e})") from None

    def xml(name: str):
        return ET.fromstring(zf.read(name))

    shared: list[str] = []
    if "xl/sharedStrings.xml" in zf.namelist():
        for si in xml("xl/sharedStrings.xml").findall("m:si", _NS):
            shared.append("".join(t.text or "" for t in si.iter(f"{{{_NS['m']}}}t")))

    rels = {
        r.get("Id"): r.get("Target")
        for r in xml("xl/_rels/workbook.xml.rels").findall("rel:Relationship", _NS)
    }

    def sheet_path(target: str) -> str:
        return target.lstrip("/") if target.startswith("/") else "xl/" + target

    def reader(name: str):
        def rows():
            for row in xml(name).iter(f"{{{_NS['m']}}}row"):
                values: list[object] = []
                for c in row.findall("m:c", _NS):
                    idx = _col_index(c.get("r", "")) if c.get("r") else len(values)
                    values.extend([None] * (idx - len(values)))
                    kind = c.get("t")
                    v = c.find("m:v", _NS)
                    if kind == "s" and v is not None:
                        value: object = shared[int(v.text)]
                    elif kind == "inlineStr":
                        value = "".join(t.text or "" for t in c.iter(f"{{{_NS['m']}}}t"))
                    else:
                        value = v.text if v is not None else None
                    values.append(value)
                yield tuple(values)

        return rows

    sheets = {}
    for sh in xml("xl/workbook.xml").find("m:sheets", _NS):
        rid = sh.get(f"{{{_NS['r']}}}id")
        sheets[sh.get("name")] = reader(sheet_path(rels[rid]))
    if not sheets:
        raise StyleMapError(f"{path}: workbook has no sheets")
    return sheets


def load_style_map(
    path: str | Path,
    sheet: str | None = None,
    key_column: str | None = None,
    ignore_columns: tuple[str, ...] | list[str] = (),
    raw: bool = False,
    keep_approx: bool = True,
) -> dict[str, dict[str, str]]:
    sheets = _read_xlsx(path)
    if sheet is not None and sheet not in sheets:
        raise StyleMapError(f"{path}: sheet {sheet!r} not found (have {list(sheets)})")
    title = sheet if sheet is not None else next(iter(sheets))
    rows = iter(sheets[title]())

    try:
        header = [_cell(h) for h in next(rows)]
    except StopIteration:
        raise StyleMapError(f"{path}: sheet {title!r} is empty") from None

    if key_column is None:
        key_idx = 0
    elif key_column in header:
        key_idx = header.index(key_column)
    else:
        raise StyleMapError(f"{path}: key column {key_column!r} not found (have {header})")

    unknown = [c for c in ignore_columns if c not in header]
    if unknown:
        raise StyleMapError(f"{path}: ignore column(s) {unknown} not found (have {header})")

    providers = [
        (i, name if raw else provider_key(name))
        for i, name in enumerate(header)
        if i != key_idx and name and name not in ignore_columns
    ]
    if not providers:
        raise StyleMapError(f"{path}: no provider columns next to the key column")
    names = [name for _, name in providers]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise StyleMapError(f"{path}: duplicate provider columns {dupes}")

    result: dict[str, dict[str, str]] = {}
    for line_no, row in enumerate(rows, start=2):
        key = _cell(row[key_idx]) if key_idx < len(row) else ""
        if not key:
            continue  # blank spacer row
        if key in result:
            raise StyleMapError(f"{path}: duplicate key {key!r} on row {line_no}")
        entry: dict[str, str] = {}
        for i, name in providers:
            value = _cell(row[i]) if i < len(row) else ""
            if value and not raw:
                value = bare_tag(value, keep_approx) or ""
            if value:
                entry[name] = value
        result[key] = entry
    return result


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("xlsx", type=Path)
    p.add_argument("--sheet", help="sheet name (default: first sheet)")
    p.add_argument("--key-column", help="header of the key column (default: first column)")
    p.add_argument(
        "--ignore-column",
        action="append",
        default=[],
        help="column that is not a provider, e.g. Category (repeatable)",
    )
    p.add_argument("--raw", action="store_true", help="keep provider headers and cell values as written")
    p.add_argument("--no-approx", action="store_true", help='drop approximate "≈ ..." entries')
    p.add_argument("--out", type=Path, help="write JSON here instead of stdout")
    args = p.parse_args(argv)

    try:
        mapping = load_style_map(
            args.xlsx, args.sheet, args.key_column, args.ignore_column, args.raw, not args.no_approx
        )
    except StyleMapError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    text = json.dumps(mapping, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"wrote {len(mapping)} keys to {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
