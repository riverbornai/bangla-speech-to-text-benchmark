from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook

ZWJ_TEXT = "র‍যাব"  # deliberate ZWJ; must survive loading untouched

HEADER = ["id", "text", "spoken_form", "accepted_variants", "category", "subcategory", "domain", "difficulty"]
ROWS = [
    ["BN-PLN-002", "না।", "না।", None, "plain", "short", "general", 1],
    ["BN-PLN-001", "হ্যাঁ।", "হ্যাঁ।", None, "plain", "short", "general", 1],
    ["BN-EDG-001", ZWJ_TEXT, ZWJ_TEXT, "a|b", "edge_cases", "zwj", "general", 3],
    ["BN-NUM-010", " স্কুলটি এখান থেকে ৫ কি.মি. দূরে। ", "x", None, "numbers", "unit", "general", 2],
]


def write_xlsx(path: Path, rows: list[list], header: list[str] = HEADER) -> Path:
    wb = Workbook()
    wb.active.title = "README"
    ws = wb.create_sheet("Dataset")
    ws.append(header)
    for r in rows:
        ws.append(r)
    ws.append([None] * len(header))
    wb.save(path)
    return path


@pytest.fixture
def dataset_xlsx(tmp_path: Path) -> Path:
    return write_xlsx(tmp_path / "dataset.xlsx", ROWS)


@pytest.fixture
def providers_yaml(tmp_path: Path) -> Path:
    path = tmp_path / "providers.yaml"
    path.write_text(
        """
providers:
  elevenlabs:
    language_code: bn
    model: eleven_v4
    voice: {id: voice123, name: george}
    output_format: mp3_44100_128
    voice_settings: {stability: 0.1, similarity_boost: 0.75}
    max_chars: 20
    price: {unit: per_1m_chars, usd_per_unit: 100.0, price_checked: "2026-10-02"}
  unverified:
    model: VERIFY_model
    voice: {id: VERIFY_voice}
    output_format: pcm_24000
""",
        encoding="utf-8",
    )
    return path
