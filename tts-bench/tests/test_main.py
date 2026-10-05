from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

import runner.main
from runner.main import parse_args, run

URL = "https://api.elevenlabs.io/v1/text-to-speech/voice123"
RUN_DIR = "runs/20261002-1200-abc1234/elevenlabs/eleven_v4/george/batch"


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    monkeypatch.delenv("RUN_ID", raising=False)
    # Fake mp3 bytes can't be probed; real ffprobe is covered in test_audio_seconds.py.
    monkeypatch.setattr(runner.main, "probe_seconds", lambda audio, fmt: 2.0)


def _args(dataset: Path, config: Path, out: Path, *extra: str):
    return parse_args(
        ["--provider", "elevenlabs", "--dataset", str(dataset), "--config", str(config),
         "--out", str(out), "--run-id", "20261002-1200-abc1234", *extra]
    )  # fmt: skip


def _manifest(out: Path, run_dir: str = RUN_DIR) -> list[dict]:
    lines = (out / run_dir / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


@respx.mock
def test_end_to_end_and_resume(dataset_xlsx: Path, providers_yaml: Path, tmp_path: Path) -> None:
    out = tmp_path / "audio"
    route = respx.post(URL).mock(
        return_value=httpx.Response(200, content=b"\x00\x00" * 24000, headers={"request-id": "r"})
    )

    assert run(_args(dataset_xlsx, providers_yaml, out)) == 0
    # 4 rows; BN-NUM-010 exceeds max_chars=20 -> unsupported and never sent.
    assert route.call_count == 3
    records = _manifest(out)
    assert [r["item_id"] for r in records] == ["BN-EDG-001", "BN-NUM-010", "BN-PLN-001", "BN-PLN-002"]
    assert [r["status"] for r in records] == ["ok", "unsupported", "ok", "ok"]
    ok = records[0]
    assert ok["audio_seconds"] == 2.0 and ok["format"] == "mp3"
    assert ok["mode"] == "batch" and 0 <= ok["ttfb_ms"] <= ok["total_ms"]
    assert ok["rtf"] == pytest.approx(ok["total_ms"] / 1000 / 2.0, abs=1e-4)
    assert ok["est_cost_usd"] == pytest.approx(ok["billed_chars"] * 100.0 / 1_000_000)
    assert (out / ok["audio_path"]).stat().st_size == 48000
    assert ok["audio_path"] == f"{RUN_DIR}/BN-EDG-001.mp3"
    run_config = json.loads((out / RUN_DIR / "run_config.json").read_text())
    assert run_config["provider_config"]["model"] == "eleven_v4"
    assert run_config["runtime"]["cpu_count"]

    # Re-running the same run_id must not re-bill: no new HTTP calls, ok records preserved.
    assert run(_args(dataset_xlsx, providers_yaml, out)) == 0
    assert route.call_count == 3
    rerun = _manifest(out)
    assert [r for r in rerun if r["status"] == "ok"] == [r for r in records if r["status"] == "ok"]


@respx.mock
def test_limit_and_exit_code_on_errors(dataset_xlsx: Path, providers_yaml: Path, tmp_path: Path) -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(400, json={"detail": {"status": "bad_request"}}))
    assert run(_args(dataset_xlsx, providers_yaml, tmp_path, "--limit", "1")) == 1
    assert route.call_count == 1
    records = _manifest(tmp_path)
    assert len(records) == 1
    assert records[0]["status"] == "error" and records[0]["http_status"] == 400


@respx.mock
def test_unmeasurable_duration_fails_item(
    dataset_xlsx: Path, providers_yaml: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner.main, "probe_seconds", lambda audio, fmt: None)
    respx.post(URL).mock(return_value=httpx.Response(200, content=b"not audio"))
    assert run(_args(dataset_xlsx, providers_yaml, tmp_path, "--limit", "1")) == 1
    [rec] = _manifest(tmp_path)
    assert rec["status"] == "error" and rec["error"] == "audio_duration_unmeasurable"
    assert rec["rtf"] is None and rec["audio_path"] is None
    assert not (tmp_path / RUN_DIR / "BN-EDG-001.mp3").exists()


@respx.mock
def test_batch_and_stream_write_separate_runs(
    dataset_xlsx: Path, providers_yaml: Path, tmp_path: Path
) -> None:
    batch = respx.post(URL).mock(return_value=httpx.Response(200, content=b"b" * 100))
    stream = respx.post(f"{URL}/stream").mock(return_value=httpx.Response(200, content=b"s" * 100))
    assert run(_args(dataset_xlsx, providers_yaml, tmp_path, "--limit", "1", "--batch", "--stream")) == 0
    assert batch.call_count == 1 and stream.call_count == 1

    stream_dir = RUN_DIR.removesuffix("batch") + "stream"
    [b], [s] = _manifest(tmp_path), _manifest(tmp_path, stream_dir)
    assert (b["mode"], s["mode"]) == ("batch", "stream")
    assert s["audio_path"] == f"{stream_dir}/BN-EDG-001.mp3"
    assert json.loads((tmp_path / stream_dir / "run_config.json").read_text())["mode"] == "stream"


@respx.mock
def test_stream_only(dataset_xlsx: Path, providers_yaml: Path, tmp_path: Path) -> None:
    batch = respx.post(URL).mock(return_value=httpx.Response(200, content=b"b"))
    stream = respx.post(f"{URL}/stream").mock(return_value=httpx.Response(200, content=b"s"))
    assert run(_args(dataset_xlsx, providers_yaml, tmp_path, "--limit", "1", "--stream")) == 0
    assert batch.call_count == 0 and stream.call_count == 1
    assert not (tmp_path / RUN_DIR).exists()
