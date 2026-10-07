from __future__ import annotations

import argparse
import io
import json
import logging
import os
import subprocess
import sys
import tempfile
import wave
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

from runner.config import ConfigError, ProviderConfig, load_provider_config
from runner.dataset import DatasetError, DatasetItem, load_dataset
from runner.emotion import TagMap, load_tag_map, style_values, tag_map_path, translate_tags
from runner.providers import create_provider
from runner.providers.base import MODES, Mode, ProviderError, TTSProvider
from runner.storage import Manifest, RunLayout, write_once

log = logging.getLogger("runner")

VARIANTS = ("baseline", "emotive")

MANIFEST_KEYS = (
    "run_id", "provider", "model", "voice", "item_id", "text", "spoken_form", "accepted_variants", "status",
    "audio_path", "format",
    "sample_rate", "bytes", "audio_seconds", "mode", "ttfb_ms", "total_ms", "rtf",
    "input_chars", "billed_chars", "est_cost_usd", "http_status", "provider_request_id", "error",
    "attempts", "started_at", "sdk_version",
)  # fmt: skip
LOG_KEYS = (
    "run_id", "provider", "mode", "item_id", "status", "ttfb_ms", "total_ms", "rtf", "http_status", "error",
)  # fmt: skip


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {"severity": record.levelname, "message": record.getMessage()}
        payload.update(getattr(record, "fields", {}))
        return json.dumps(payload, ensure_ascii=False)


def _log(level: int, message: str, **fields: Any) -> None:
    log.log(level, message, extra={"fields": fields})


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _git_sha() -> str:
    if sha := os.environ.get("GIT_SHA"):
        return sha[:7]
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short=7", "HEAD"], capture_output=True, text=True, check=True
        )
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "nogit"


def resolve_run_id(cli_value: str | None) -> str:
    if cli_value:
        return cli_value
    return f"{datetime.now(UTC):%Y%m%d-%H%M}-{_git_sha()}"


def probe_seconds(audio: bytes, fmt: str) -> float | None:
    """Duration of compressed audio (mp3/ogg/flac) via ffprobe; None if it can't be read."""
    # A local temp file (not the FUSE mount) lets ffprobe seek, which pipes don't allow.
    with tempfile.NamedTemporaryFile(suffix=f".{fmt}") as f:
        f.write(audio)
        f.flush()
        try:
            out = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", f.name],
                capture_output=True, text=True, check=True, timeout=30,
            )  # fmt: skip
            return float(out.stdout.strip())
        except (OSError, subprocess.SubprocessError, ValueError):
            return None


def audio_seconds(audio: bytes, fmt: str, sample_rate: int) -> float | None:
    """Duration measured from the returned audio, never estimated from text."""
    if fmt == "pcm":
        seconds: float | None = len(audio) / (2 * sample_rate)  # s16le mono
    elif fmt == "wav":
        try:
            with wave.open(io.BytesIO(audio)) as w:
                seconds = w.getnframes() / w.getframerate()
        except (wave.Error, EOFError):
            seconds = probe_seconds(audio, fmt)
    else:
        seconds = probe_seconds(audio, fmt)
    return round(seconds, 3) if seconds and seconds > 0 else None


def _cgroup_memory_bytes() -> int | None:
    try:
        value = Path("/sys/fs/cgroup/memory.max").read_text().strip()
        return int(value) if value.isdigit() else None
    except OSError:
        return None


def _cloud_run_region() -> str | None:
    if not os.environ.get("CLOUD_RUN_JOB"):
        return None
    try:
        resp = httpx.get(
            "http://metadata.google.internal/computeMetadata/v1/instance/region",
            headers={"Metadata-Flavor": "Google"},
            timeout=2.0,
        )
        return resp.text.rsplit("/", 1)[-1] if resp.status_code == 200 else None
    except httpx.HTTPError:
        return None


def runtime_context() -> dict[str, Any]:
    """Where latency was measured: network distance to the provider is part of TTFB."""
    return {
        "region": _cloud_run_region(),
        "cloud_run_job": os.environ.get("CLOUD_RUN_JOB"),
        "cloud_run_execution": os.environ.get("CLOUD_RUN_EXECUTION"),
        "cpu_count": os.cpu_count(),
        "memory_limit_bytes": _cgroup_memory_bytes(),
    }


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    env = os.environ.get
    p = argparse.ArgumentParser(
        prog="runner.main", description="Synthesize every dataset row with one model."
    )
    # Per-run choices come from the CLI (Cloud Run: --args); fixed infra paths may come from env.
    p.add_argument("--provider", required=True, help="key in providers.yaml, e.g. elevenlabs, sarvam")
    p.add_argument("--dataset", default=env("DATASET_PATH"), required=env("DATASET_PATH") is None)
    p.add_argument("--out", default=env("AUDIO_ROOT"), required=env("AUDIO_ROOT") is None)
    p.add_argument("--config", default=env("PROVIDER_CONFIG_PATH", "config/providers.yaml"))
    p.add_argument("--run-id", default=None, help="reuse an id to resume; default YYYYMMDD-HHMM-<sha>")
    p.add_argument("--limit", type=int, default=None, help="only the first N rows (sorted by id)")
    p.add_argument("--batch", action="store_true", help="non-streaming endpoint (default if no mode given)")
    p.add_argument("--stream", action="store_true", help="streaming endpoint; with --batch, runs both")
    p.add_argument(
        "--variant", choices=VARIANTS, default="baseline",
        help="emotive: send text_emotive with its [keys] translated to the model's own tags",
    )  # fmt: skip
    p.add_argument(
        "--tag-map", default=None, help="tag map for --variant emotive; default config/<provider>.json"
    )
    p.add_argument("--dry-run", action="store_true", help="print the text that would be sent; no API calls")
    p.add_argument(
        "--dry-run-out", default=None, help="also write the dry run to this .jsonl file (implies --dry-run)"
    )
    p.add_argument("--max-error-rate", type=float, default=float(env("MAX_ERROR_RATE", "0.2")))
    return p.parse_args(argv)


def emotive_items(items: list[DatasetItem], tag_map: TagMap) -> list[DatasetItem]:
    """`--variant emotive`: the text sent is `text_emotive` with each [key] swapped for the model's text.

    The result replaces `text`, so the manifest records exactly what was sent; `spoken_form` stays the CER
    reference because tags must not be spoken.
    """
    out = []
    for item in items:
        if not item.text_emotive:
            raise DatasetError(f"{item.item_id}: empty text_emotive (needed for --variant emotive)")
        text = translate_tags(item.text_emotive, tag_map)
        if not text:
            raise DatasetError(f"{item.item_id}: nothing left of text_emotive after removing unmapped tags")
        out.append(replace(item, text=text))
    return out


def dry_run(
    source: list[DatasetItem],
    sent: list[DatasetItem],
    config: ProviderConfig,
    modes: list[Mode],
    variant: str,
    out: Path | None,
) -> None:
    """Show what a real run would send; no provider is created and no API is called."""
    records = []
    for src, item in zip(source, sent, strict=True):
        too_long = config.max_chars is not None and len(item.text) > config.max_chars
        print(
            f"{item.item_id}  {len(item.text)} chars"
            + ("  EXCEEDS max_chars: would be skipped" if too_long else "")
        )
        # What the dataset holds for this variant. Not inferred from the sent text: a provider whose tag map
        # is empty (sarvam, openai) sends text identical to `text`, but its dataset text still has the tags.
        dataset_text = src.text_emotive if variant == "emotive" else src.text
        if dataset_text != item.text:
            print(f"  dataset: {dataset_text}")
        print(f"  sent:    {item.text}")
        record_extra: dict[str, Any] = {}
        if config.emotive_styles:  # Gemini: the styles leave the text and go into the request parts
            from runner.providers.gemini.styles import build_parts

            record_extra["parts"] = build_parts(item.text, config.emotive_styles)
            print(f"  parts:   {json.dumps(record_extra['parts'], ensure_ascii=False)}")
        records.append(
            {
                "item_id": item.item_id, "provider": config.name, "model": config.model, "variant": variant,
                "category": item.category, "dataset_text": dataset_text,
                "text": item.text, "spoken_form": item.spoken_form, "input_chars": len(item.text),
                "exceeds_max_chars": too_long, **record_extra,
            }
        )  # fmt: skip
    if out is not None:
        body = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
        write_once(out, body.encode("utf-8"))
    print(
        f"\ndry run: {len(sent)} items, {config.name} / {config.model} / {'+'.join(modes)}; nothing was sent"
        + (f"; wrote {out}" if out else "")
    )


def process(
    item: DatasetItem, provider: TTSProvider, config: ProviderConfig, layout: RunLayout, manifest: Manifest
) -> dict[str, Any]:
    path = layout.audio_path(item.item_id, provider.format)
    # Exact input text and CER references, copied from the dataset so the manifest is self-contained.
    references = {
        "text": item.text, "spoken_form": item.spoken_form, "accepted_variants": list(item.accepted_variants),
    }  # fmt: skip
    rec: dict[str, Any] = dict.fromkeys(MANIFEST_KEYS)
    rec.update(
        references, run_id=layout.run_id, provider=config.name, model=config.model, voice=config.voice.name,
        item_id=item.item_id, mode=config.mode, input_chars=len(item.text), started_at=_now(),
        sdk_version=f"httpx/{httpx.__version__}", audio_path=layout.relative(path), format=provider.format,
    )  # fmt: skip

    # Resume: never re-bill an item whose audio is already on disk.
    if os.path.exists(path):
        prev = manifest.previous(item.item_id)
        if prev and prev.get("status") == "ok":
            return {**prev, **references}  # refresh references in records from older manifests
        rec.update(status="skipped_existing", bytes=os.path.getsize(path))
        return rec

    if not provider.supports(item):
        rec.update(status="unsupported", audio_path=None, error="exceeds max_chars")
        return rec

    try:
        result = provider.synthesize(item.text)
    except ProviderError as e:
        rec.update(
            status="error", audio_path=None, http_status=e.status, provider_request_id=e.request_id,
            error=str(e), attempts=e.attempts,
        )  # fmt: skip
        return rec

    timing = {
        "ttfb_ms": None if result.ttfb_ms is None else round(result.ttfb_ms, 1),
        "total_ms": round(result.total_ms, 1), "billed_chars": result.billed_chars,
        "est_cost_usd": config.estimate_cost(result.billed_chars), "http_status": 200,
        "provider_request_id": result.request_id, "attempts": result.attempts,
    }  # fmt: skip
    seconds = audio_seconds(result.audio, result.format, result.sample_rate)
    if seconds is None:
        # Without a duration there is no RTF; fail the item rather than write rtf: null.
        rec.update(timing, status="error", audio_path=None, error="audio_duration_unmeasurable")
        return rec

    write_once(path, result.audio)
    rec.update(
        timing, status="ok", sample_rate=result.sample_rate, bytes=len(result.audio),
        audio_seconds=seconds, rtf=round(result.total_ms / 1000 / seconds, 4),
    )  # fmt: skip
    return rec


def selected_modes(args: argparse.Namespace) -> list[Mode]:
    return [m for m in MODES if getattr(args, m)] or ["batch"]


def run_mode(
    args: argparse.Namespace,
    run_id: str,
    config: ProviderConfig,
    items: list[DatasetItem],
    dataset: dict[str, Any],
) -> float:
    """Synthesize every selected row with one provider in one mode; returns the error rate."""
    layout = RunLayout(Path(args.out), run_id, config.name, config.model, config.voice.name, config.mode)
    if os.path.exists(layout.run_config_path):
        # Resuming would skip rows already on disk, so never mix variants in one run directory.
        existing = json.loads(Path(layout.run_config_path).read_text(encoding="utf-8")).get("variant")
        if existing != args.variant:
            raise ConfigError(
                f"{layout.run_dir} holds a {existing!r} run; use a new --run-id for {args.variant!r}"
            )
    else:
        run_config = {
            "run_id": run_id, "created_at": _now(), "git_sha": _git_sha(), "variant": args.variant,
            "mode": config.mode, **dataset, "limit": args.limit,
            "provider_config": config.__dict__ | {"voice": config.voice.__dict__},
            "non_default_settings": {"voice_settings": config.voice_settings},
            "runtime": runtime_context(),
        }  # fmt: skip
        write_once(layout.run_config_path, json.dumps(run_config, ensure_ascii=False, indent=2).encode())

    provider = create_provider(config)
    manifest = Manifest(layout.manifest_path)
    counts: dict[str, int] = {}
    try:
        for item in items:
            rec = process(item, provider, config, layout, manifest)
            manifest.add(rec)
            counts[rec["status"]] = counts.get(rec["status"], 0) + 1
            level = logging.WARNING if rec["status"] == "error" else logging.INFO
            _log(level, "item done", **{k: rec[k] for k in LOG_KEYS})
    finally:
        manifest.flush()
        provider.close()

    attempted = counts.get("ok", 0) + counts.get("error", 0)
    error_rate = counts.get("error", 0) / attempted if attempted else 0.0
    _log(
        logging.INFO, "mode finished", run_id=run_id, provider=config.name, mode=config.mode,
        counts=counts, error_rate=error_rate,
    )  # fmt: skip
    return error_rate


def run(args: argparse.Namespace) -> int:
    run_id = resolve_run_id(args.run_id)
    # Load every mode's config before the first paid call, so a bad config fails fast.
    configs = [load_provider_config(args.config, args.provider, mode) for mode in selected_modes(args)]
    dataset_path = Path(args.dataset)
    items = load_dataset(dataset_path)
    total_rows = len(items)
    if args.limit is not None:
        items = items[: args.limit]
    sent = items
    if args.variant == "emotive":
        tag_map = load_tag_map(args.tag_map or tag_map_path(args.config, args.provider))
        sent = emotive_items(items, tag_map)
        # Gemini sends its `style` tags as speech_metadata; other providers have none.
        configs = [replace(c, emotive_styles=style_values(tag_map)) for c in configs]
    if args.dry_run or args.dry_run_out:
        out = Path(args.dry_run_out) if args.dry_run_out else None
        dry_run(items, sent, configs[0], [c.mode for c in configs], args.variant, out)
        return 0
    items = sent
    dataset = {
        "dataset": str(dataset_path), "dataset_rows": total_rows,
        "dataset_mtime": datetime.fromtimestamp(dataset_path.stat().st_mtime, UTC).isoformat(),
    }  # fmt: skip
    _log(
        logging.INFO, "dataset loaded", run_id=run_id, provider=args.provider, model=configs[0].model,
        modes=[c.mode for c in configs], rows=total_rows, selected=len(items), **dataset,
    )  # fmt: skip

    error_rates = [run_mode(args, run_id, config, items, dataset) for config in configs]
    return 1 if any(rate > args.max_error_rate for rate in error_rates) else 0


def main(argv: list[str] | None = None) -> None:
    load_dotenv()  # API keys from .env (baked into the image); real env vars take precedence
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    logging.getLogger("httpx").setLevel(logging.WARNING)  # its INFO lines include full URLs
    args = parse_args(argv)
    try:
        sys.exit(run(args))
    except (ConfigError, DatasetError) as e:
        _log(logging.ERROR, str(e))
        sys.exit(2)


if __name__ == "__main__":
    main()
