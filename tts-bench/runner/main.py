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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

from runner.config import ConfigError, ProviderConfig, load_provider_config
from runner.dataset import DatasetError, DatasetItem, load_dataset
from runner.providers import create_provider
from runner.providers.base import MODES, Mode, ProviderError, TTSProvider
from runner.storage import Manifest, RunLayout, write_once

log = logging.getLogger("runner")

MANIFEST_KEYS = (
    "run_id", "provider", "model", "voice", "item_id", "status", "audio_path", "format",
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
    p.add_argument("--max-error-rate", type=float, default=float(env("MAX_ERROR_RATE", "0.2")))
    return p.parse_args(argv)


def process(
    item: DatasetItem, provider: TTSProvider, config: ProviderConfig, layout: RunLayout, manifest: Manifest
) -> dict[str, Any]:
    path = layout.audio_path(item.item_id, provider.format)
    rec: dict[str, Any] = dict.fromkeys(MANIFEST_KEYS)
    rec.update(
        run_id=layout.run_id, provider=config.name, model=config.model, voice=config.voice.name,
        item_id=item.item_id, mode=config.mode, input_chars=len(item.text), started_at=_now(),
        sdk_version=f"httpx/{httpx.__version__}", audio_path=layout.relative(path), format=provider.format,
    )  # fmt: skip

    # Resume: never re-bill an item whose audio is already on disk.
    if os.path.exists(path):
        prev = manifest.previous(item.item_id)
        if prev and prev.get("status") == "ok":
            return prev
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
        "ttfb_ms": round(result.ttfb_ms, 1),
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
    if not os.path.exists(layout.run_config_path):
        run_config = {
            "run_id": run_id, "created_at": _now(), "git_sha": _git_sha(), "variant": "baseline",
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
