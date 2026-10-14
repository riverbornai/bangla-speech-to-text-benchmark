"""Repair runs made before the WAV fix: re-wrap each WAV with a correct header and recompute the manifest.

Older clips (OpenAI, Cartesia, Soniox, Sarvam) carry a placeholder data length, so `audio_seconds` came out as
89478 and `rtf` as 0.0; older Gemini clips also end with a burst of static (its C2PA metadata chunk). The audio
itself is fine: this rewrites the header, drops that trailer, and recomputes `bytes`, `audio_seconds`, `rtf`.

    python -m runner.repair_wav --out /mnt/audio/tts-bench --run-id openai-prod            # report only
    python -m runner.repair_wav --out /mnt/audio/tts-bench --run-id openai-prod --apply    # rewrite
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from runner.main import audio_seconds
from runner.providers.base import to_wav


def repair_manifest(manifest: Path, out: Path, apply: bool) -> tuple[int, int]:
    """Returns (rows checked, rows changed)."""
    lines = manifest.read_text(encoding="utf-8").splitlines()
    rows = [json.loads(line) for line in lines if line.strip()]
    checked = changed = 0
    for row in rows:
        if row.get("status") != "ok" or row.get("format") != "wav":
            continue
        checked += 1
        path = out / row["audio_path"]
        old = path.read_bytes()
        new = to_wav(old, row["sample_rate"])
        seconds = audio_seconds(new, "wav", row["sample_rate"])
        if new == old and seconds == row["audio_seconds"]:
            continue
        changed += 1
        print(f"{row['item_id']}: {row['audio_seconds']} s -> {seconds} s, {len(old)} -> {len(new)} bytes")
        if apply and seconds:
            path.write_bytes(new)
            row.update(bytes=len(new), audio_seconds=seconds, rtf=round(row["total_ms"] / 1000 / seconds, 4))
    if apply and changed:
        manifest.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return checked, changed


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, type=Path, help="the output root the runner used (has runs/)")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--apply", action="store_true", help="rewrite the files (default: only report)")
    args = ap.parse_args()

    manifests = sorted((args.out / "runs" / args.run_id).glob("*/*/*/*/manifest.jsonl"))
    if not manifests:
        raise SystemExit(f"no manifests under {args.out / 'runs' / args.run_id}")
    total = 0
    for manifest in manifests:
        print(f"== {manifest.relative_to(args.out)}")
        checked, changed = repair_manifest(manifest, args.out, args.apply)
        print(f"   {checked} wav rows, {changed} {'fixed' if args.apply else 'to fix'}")
        total += changed
    if total and not args.apply:
        print("re-run with --apply to rewrite them")


if __name__ == "__main__":
    main()
