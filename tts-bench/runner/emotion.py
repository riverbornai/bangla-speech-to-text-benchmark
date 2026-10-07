"""Translate the dataset's emotion keys (`[laugh]`) into the text one model expects.

Each provider has `config/<provider>.json` mapping a key to the exact replacement text, e.g.
`"laugh": "[laughs]"` for ElevenLabs. The replacement is used verbatim, whatever its syntax.
Gemini entries are `{"tag_type": "style" | "tag", "value": ...}`: a `tag` is replaced inline like the
others, a `style` is written as `[value]` and the Gemini provider turns it into `speech_metadata.style`.
A key with no entry for the provider becomes an empty string (the model has no equivalent).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from runner.config import ConfigError

# Only ASCII keys are tags; a bracketed Bangla word such as [বিজ্ঞপ্তি] is dataset content and stays.
# The whitespace after a tag is captured so removing the tag does not leave a gap.
_TAG = re.compile(r"\[([A-Za-z_]+)\](\s*)")

TagMap = dict[str, Any]  # key -> replacement string, or {"tag_type": ..., "value": ...} (Gemini)


def tag_map_path(config_path: str | Path, provider: str) -> Path:
    return Path(config_path).parent / f"{provider}.json"


def load_tag_map(path: str | Path) -> TagMap:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(
            f"tag map not found: {path} (the emotive variant needs config/<provider>.json)"
        ) from None
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: expected an object mapping key -> replacement")
    for key, entry in data.items():
        if isinstance(entry, str):
            continue
        if not (isinstance(entry, dict) and entry.get("tag_type") in ("style", "tag") and entry.get("value")):
            raise ConfigError(f"{path}: {key!r} must be a string or {{tag_type: style|tag, value: ...}}")
    return data


def style_values(tag_map: TagMap) -> tuple[str, ...]:
    """The values that become `speech_metadata.style` (Gemini); empty for every other provider."""
    values = {e["value"] for e in tag_map.values() if isinstance(e, dict) and e["tag_type"] == "style"}
    return tuple(sorted(values))


def _replacement(entry: Any) -> str:
    if entry is None:
        return ""
    if isinstance(entry, str):
        return entry
    return f"[{entry['value']}]" if entry["tag_type"] == "style" else entry["value"]


def translate_tags(text: str, tag_map: TagMap) -> str:
    """Replace every `[key]` with the provider's text for it, or remove it when there is none."""
    removed = False

    def swap(match: re.Match[str]) -> str:
        nonlocal removed
        value = _replacement(tag_map.get(match.group(1)))
        if not value:
            removed = True
            return ""  # also drops the space that followed the tag
        return value + match.group(2)

    out = _TAG.sub(swap, text)
    return out.strip() if removed else out
