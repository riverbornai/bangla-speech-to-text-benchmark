"""
Build a per-model emotion-tag mapping from the TTS emotion tag dictionary (xlsx).

    python utils.py tts-emotion-tag-dictionary.xlsx --model elevenlabs
    python utils.py tts-emotion-tag-dictionary.xlsx --model cartesia --out cartesia.json
    python utils.py tts-emotion-tag-dictionary.xlsx --model gemini --include-approx

Supported models: elevenlabs, gemini, cartesia, soniox.

Output keys are the dataset keys (e.g. "happy", "scared_fearful", "clear_throat").
Values:
  - ElevenLabs / Soniox keep square brackets:   "[happy]"
  - Cartesia's [laughter] is returned bare:     "laughter"
  - XML / angle-bracket tags are returned as-is: '<speed ratio="1.3"/>'
  - "—" (not supported) is left out
  - "≈ ..." (workaround) is left out unless --include-approx is given,
    and even then only if the workaround is an actual tag ([..] or <..>)
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import openpyxl

SHEET = "Tag Dictionary"
KEY_COLUMN = "Common Tag"

# Only these four models are supported.
SUPPORTED = ("elevenlabs", "gemini", "cartesia", "soniox")

# short names people type -> canonical model name (also matched against the column header)
MODEL_ALIASES = {
    "elevenlabs": "elevenlabs", "eleven": "elevenlabs", "11labs": "elevenlabs",
    "gemini": "gemini",
    "cartesia": "cartesia", "cartisian": "cartesia", "sonic": "cartesia",
    "soniox": "soniox",
}

UNSUPPORTED = {"—", "-", "", None}
PARAM_RE = re.compile(r'^([a-z_]+):\s*"?([^"]+)"?$')      # Gemini: style: "happy"


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def to_key(common_tag: str) -> str:
    """'scared / fearful' -> 'scared_fearful', 'clear throat' -> 'clear_throat'."""
    return re.sub(r"[^a-z0-9]+", "_", common_tag.strip().lower()).strip("_")


def _clean(value: str) -> str:
    v = value.strip()
    m = re.fullmatch(r"\[([^\[\]]+)\]", v)          # [happy] -> happy
    return m.group(1).strip() if m else v


def _is_tag(value: str) -> bool:
    v = value.strip()
    return bool(re.fullmatch(r"\[[^\[\]]+\]", v) or re.fullmatch(r"<[^<>]+>", v))


def find_column(headers: list[str], model: str) -> int:
    want = MODEL_ALIASES.get(_norm(model))
    if want not in SUPPORTED:
        raise SystemExit(f"Model '{model}' not supported. Use one of: {', '.join(SUPPORTED)}")
    hits = [i for i, h in enumerate(headers) if h and want in _norm(h)]
    if not hits:
        raise SystemExit(f"Column for '{want}' not found in the dictionary sheet.")
    return hits[0]


def _gemini_entry(value: str) -> dict[str, str]:
    """Gemini: <...> values are inline tags, style: "..." values go to speech_metadata.style."""
    if value.startswith("<"):
        return {"tag_type": "tag", "value": value}
    pm = PARAM_RE.match(value)
    return {"tag_type": "style", "value": pm.group(2).strip() if pm else value}


def load_mapping(xlsx_path: str | Path, model: str, include_approx: bool = False) -> dict:
    """Return {dataset_key: model_tag} for one model.

    For Gemini each value is {"tag_type": "tag" | "style", "value": ...}:
      "laugh": {"tag_type": "tag",   "value": "<laugh>"}
      "happy": {"tag_type": "style", "value": "happy"}
    """
    ws = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)[SHEET]
    rows = ws.iter_rows(values_only=True)
    headers = [str(h).strip() if h else "" for h in next(rows)]
    key_col = headers.index(KEY_COLUMN)
    col = find_column(headers, model)

    canon = MODEL_ALIASES.get(_norm(model))
    is_gemini = canon == "gemini"
    keep_brackets = canon in ("elevenlabs", "soniox")      # values returned as "[happy]"
    mapping: dict = {}
    for row in rows:
        common = row[key_col]
        if not common or row[0] in (None, "Legend"):
            if row[0] == "Legend":
                break
            continue
        raw = row[col]
        raw = raw.strip() if isinstance(raw, str) else raw
        if raw in UNSUPPORTED:
            continue
        if raw.startswith("≈"):
            if not include_approx:
                continue
            raw = raw.lstrip("≈").strip()
            if not _is_tag(raw):          # e.g. "≈ punctuation (!)" is not usable as a tag
                continue
        if not (_is_tag(raw) or PARAM_RE.match(raw)):   # e.g. "pitch (v2 only)" is a note, not a tag
            continue
        value = raw if keep_brackets and _is_tag(raw) else _clean(raw)
        mapping[to_key(common)] = _gemini_entry(value) if is_gemini else value
    return mapping


def apply_tags(text: str, mapping: dict) -> tuple[str, dict[str, str]]:
    """Replace dataset tags like [happy] with the model's syntax.

    Returns (text, params):
      - bare values    -> "[value]" inline   (ElevenLabs, Soniox, Cartesia [laughter])
      - XML tags       -> inserted inline    (Cartesia <emotion/>, <speed/>, <break/>; Gemini <sigh>)
      - Gemini tag_type "style" -> params["style"] (send in speech_metadata.style, not inline)
      - Gemini tag_type "tag"   -> inserted inline
      - keys the model doesn't support are removed
    Bangla text in brackets such as [বিজ্ঞপ্তি] is left untouched.
    """
    params: dict[str, str] = {}

    def sub(m: re.Match) -> str:
        v = mapping.get(m.group(1))
        if v is None:
            return ""
        if isinstance(v, dict):                                   # Gemini
            if v["tag_type"] == "style":
                params["style"] = f"{params['style']}, {v['value']}" if "style" in params else v["value"]
                return ""
            return v["value"]
        pm = PARAM_RE.match(v)
        if pm and not v.startswith("<"):
            name, val = pm.groups()
            params[name] = f"{params[name]}, {val}" if name in params else val
            return ""
        return v if v.startswith(("<", "[")) else f"[{v}]"

    out = re.sub(r"\[([a-z0-9_]+)\]", sub, text)
    return re.sub(r"\s{2,}", " ", out).strip(), params


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("xlsx", help="tts-emotion-tag-dictionary.xlsx")
    ap.add_argument("--model", required=True, help="elevenlabs | gemini | cartesia | soniox")
    ap.add_argument("--include-approx", action="store_true", help="also include ≈ workarounds that are real tags")
    ap.add_argument("--out", help="write JSON to this file instead of stdout")
    args = ap.parse_args()

    mapping = load_mapping(args.xlsx, args.model, args.include_approx)
    js = json.dumps(mapping, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(js, encoding="utf-8")
        print(f"{len(mapping)} tags -> {args.out}")
    else:
        print(js)


if __name__ == "__main__":
    main()