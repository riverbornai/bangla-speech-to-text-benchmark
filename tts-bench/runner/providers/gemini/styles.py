"""Adapter: dataset text with leading `[style]` tags -> Gemini `Part`s with `speech_metadata`.

`"[laugh] হাসির কথা। সাধারণ বাক্য। [whisper] ফিসফিস।"` becomes three-and-a-bit parts:
`{"text": "হাসির কথা। সাধারণ বাক্য।", "speech_metadata": {"style": "laugh"}}` and
`{"text": "ফিসফিস।", "speech_metadata": {"style": "whisper"}}`.
Untagged sentences stay in a plain part (merged with their untagged neighbours).
"""

from __future__ import annotations

import re
from collections.abc import Collection
from typing import Any

# Style tags are always a single English word (e.g. "[laugh]"); anything else, like the Bangla bracket
# "[বিজ্ঞপ্তি]", is dataset content and left as text.
_TAG = re.compile(r"\[(?P<style>[A-Za-z]+)\]")
_SENTENCE_END = "।?!.…"


def _starts_sentence(text: str, pos: int) -> bool:
    head = text[:pos]
    return not head.strip() or (head != head.rstrip() and head.rstrip()[-1] in _SENTENCE_END)


def split_styled(text: str) -> list[tuple[str | None, str]]:
    """Split into (style, text) segments. A tag only counts at the start of a sentence."""
    segments: list[tuple[str | None, int, int]] = []  # style, text start, tag start (= end of previous text)
    cuts = [m for m in _TAG.finditer(text) if _starts_sentence(text, m.start())]
    pos, style = 0, None
    for m in cuts:
        segments.append((style, pos, m.start()))
        pos, style = m.end(), m.group("style").strip()
    segments.append((style, pos, len(text)))
    return [(s, text[a:b].strip()) for s, a, b in segments if text[a:b].strip()]


def split_marked(text: str, styles: Collection[str]) -> list[tuple[str | None, str]]:
    """Emotive variant: split at every `[<style>]` whose value is one of `styles` (from config/gemini.json).

    Exact values only, so a bracketed Bangla word or other brackets stay text. A style applies until the
    next marker, wherever the marker sits (no sentence-start rule: the values come from our own map).
    """
    if not styles:
        return [(None, text)]
    marker = re.compile(
        r"\[(" + "|".join(re.escape(v) for v in sorted(styles, key=len, reverse=True)) + r")\]"
    )
    segments: list[tuple[str | None, str]] = []
    pos, style = 0, None
    for m in marker.finditer(text):
        segments.append((style, text[pos : m.start()]))
        pos, style = m.end(), m.group(1)
    segments.append((style, text[pos:]))
    return [(s, t.strip()) for s, t in segments if t.strip()]


def build_parts(text: str, styles: Collection[str] = ()) -> list[dict[str, Any]]:
    """`styles` empty: baseline (single-English-word tags at a sentence start). Else: emotive markers."""
    parts: list[dict[str, Any]] = []
    for style, chunk in split_marked(text, styles) if styles else split_styled(text):
        part: dict[str, Any] = {"text": chunk}
        if style:
            part["speech_metadata"] = {"style": style}
        parts.append(part)
    return parts or [{"text": text}]  # e.g. a lone "[laugh]": nothing to style, send as-is
