"""Output layout on the audio mount. Every object is written once, whole, then closed (GCS FUSE)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def write_once(path: Path, data: bytes) -> None:
    os.makedirs(path.parent, exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


@dataclass(frozen=True)
class RunLayout:
    root: Path
    run_id: str
    provider: str
    model: str
    voice: str
    mode: str

    @property
    def run_dir(self) -> Path:
        model = self.model.replace("/", "__")
        return self.root / "runs" / self.run_id / self.provider / model / self.voice / self.mode

    @property
    def manifest_path(self) -> Path:
        return self.run_dir / "manifest.jsonl"

    @property
    def run_config_path(self) -> Path:
        return self.run_dir / "run_config.json"

    def audio_path(self, item_id: str, ext: str) -> Path:
        return self.run_dir / f"{item_id}.{ext}"

    def relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()


class Manifest:
    """One JSON line per item, rewritten whole every `checkpoint_every` items and at the end."""

    def __init__(self, path: Path, checkpoint_every: int = 50) -> None:
        self.path = path
        self.checkpoint_every = checkpoint_every
        self._records: dict[str, dict[str, Any]] = {}
        self._previous: dict[str, dict[str, Any]] = {}
        self._since_flush = 0
        if os.path.exists(path):
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    rec = json.loads(line)
                    self._previous[rec["item_id"]] = rec
        self._records.update(self._previous)

    def previous(self, item_id: str) -> dict[str, Any] | None:
        return self._previous.get(item_id)

    def add(self, record: dict[str, Any]) -> None:
        self._records[record["item_id"]] = record
        self._since_flush += 1
        if self._since_flush >= self.checkpoint_every:
            self.flush()

    def flush(self) -> None:
        body = "".join(json.dumps(self._records[k], ensure_ascii=False) + "\n" for k in sorted(self._records))
        write_once(self.path, body.encode("utf-8"))
        self._since_flush = 0
