from __future__ import annotations

from pathlib import Path

import pytest
from conftest import HEADER, ROWS, ZWJ_TEXT, write_xlsx

from runner.dataset import DatasetError, load_dataset


def test_loads_sorted_and_preserves_text_exactly(dataset_xlsx: Path) -> None:
    items = load_dataset(dataset_xlsx)
    assert [i.item_id for i in items] == ["BN-EDG-001", "BN-NUM-010", "BN-PLN-001", "BN-PLN-002"]
    by_id = {i.item_id: i for i in items}
    assert by_id["BN-EDG-001"].text == ZWJ_TEXT
    assert by_id["BN-NUM-010"].text.startswith(" ") and by_id["BN-NUM-010"].text.endswith(" ")
    assert by_id["BN-EDG-001"].accepted_variants == ("a", "b")


def test_duplicate_ids_fail(tmp_path: Path) -> None:
    path = write_xlsx(tmp_path / "d.xlsx", [ROWS[0], ROWS[0]])
    with pytest.raises(DatasetError, match="duplicate id"):
        load_dataset(path)


def test_empty_text_fails(tmp_path: Path) -> None:
    path = write_xlsx(tmp_path / "d.xlsx", [["BN-X-001", "   ", "", None, "plain", None, None, 1]])
    with pytest.raises(DatasetError, match="empty"):
        load_dataset(path)


def test_missing_column_fails(tmp_path: Path) -> None:
    path = write_xlsx(tmp_path / "d.xlsx", [r[:1] for r in ROWS], header=HEADER[:1])
    with pytest.raises(DatasetError, match="missing required columns"):
        load_dataset(path)
