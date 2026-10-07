from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

import runner.main
from runner.config import ConfigError
from runner.main import parse_args, run
from tests.conftest import HEADER, write_xlsx

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
    assert ok["mode"] == "batch" and ok["ttfb_ms"] is None and ok["total_ms"] > 0
    assert ok["rtf"] == pytest.approx(ok["total_ms"] / 1000 / 2.0, abs=1e-4)
    assert ok["est_cost_usd"] == pytest.approx(ok["billed_chars"] * 100.0 / 1_000_000)
    assert (out / ok["audio_path"]).stat().st_size == 48000
    assert ok["audio_path"] == f"{RUN_DIR}/BN-EDG-001.mp3"
    assert ok["text"] == ok["spoken_form"] == "র\u200dযাব" and ok["accepted_variants"] == ["a", "b"]
    assert records[1]["text"] == " স্কুলটি এখান থেকে ৫ কি.মি. দূরে। "  # unchanged, spaces kept
    assert records[2]["accepted_variants"] == [] and records[1]["spoken_form"] == "x"  # also on unsupported
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
    assert b["ttfb_ms"] is None and 0 <= s["ttfb_ms"] <= s["total_ms"]
    assert b["rtf"] is not None and s["rtf"] is not None
    assert s["audio_path"] == f"{stream_dir}/BN-EDG-001.mp3"
    assert json.loads((tmp_path / stream_dir / "run_config.json").read_text())["mode"] == "stream"


@respx.mock
def test_stream_only(dataset_xlsx: Path, providers_yaml: Path, tmp_path: Path) -> None:
    batch = respx.post(URL).mock(return_value=httpx.Response(200, content=b"b"))
    stream = respx.post(f"{URL}/stream").mock(return_value=httpx.Response(200, content=b"s"))
    assert run(_args(dataset_xlsx, providers_yaml, tmp_path, "--limit", "1", "--stream")) == 0
    assert batch.call_count == 0 and stream.call_count == 1
    assert not (tmp_path / RUN_DIR).exists()


def _emotive_dataset(tmp_path: Path) -> Path:
    return write_xlsx(
        tmp_path / "dataset.xlsx",
        [
            ["BN-PLN-001", "হ্যাঁ।", "হ্যাঁ।", None, "plain", "short", "general", 1, "[laugh] হ্যাঁ।"],
            ["BN-PLN-002", "না।", "না।", None, "plain", "short", "general", 1, "[sigh] না। [laugh]"],
        ],
        [*HEADER, "text_emotive"],
    )


@respx.mock
def test_emotive_variant_sends_translated_text_emotive(tmp_path: Path, providers_yaml: Path) -> None:
    # config/<provider>.json sits next to providers.yaml; "sigh" has no entry, so it is removed.
    (providers_yaml.parent / "elevenlabs.json").write_text(
        json.dumps({"laugh": "[laughs]"}), encoding="utf-8"
    )
    dataset = _emotive_dataset(tmp_path)
    out = tmp_path / "audio"
    route = respx.post(URL).mock(return_value=httpx.Response(200, content=b"\x00\x00" * 24000))

    assert run(_args(dataset, providers_yaml, out, "--variant", "emotive")) == 0

    assert [json.loads(c.request.content)["text"] for c in route.calls] == ["[laughs] হ্যাঁ।", "না। [laughs]"]
    recs = _manifest(out)
    assert [r["text"] for r in recs] == ["[laughs] হ্যাঁ।", "না। [laughs]"]
    assert recs[0]["spoken_form"] == "হ্যাঁ।"  # CER reference is untagged
    assert json.loads((out / RUN_DIR / "run_config.json").read_text())["variant"] == "emotive"

    # A baseline run must not reuse (and skip rows of) the emotive run directory.
    with pytest.raises(ConfigError, match="use a new --run-id"):
        run(_args(dataset, providers_yaml, out))


@respx.mock
def test_emotive_variant_needs_a_tag_map(dataset_xlsx: Path, providers_yaml: Path, tmp_path: Path) -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(200, content=b"\x00\x00"))
    with pytest.raises(ConfigError, match="tag map not found"):
        run(_args(dataset_xlsx, providers_yaml, tmp_path / "audio", "--variant", "emotive"))
    assert route.call_count == 0


@respx.mock
def test_dry_run_prints_text_and_touches_nothing(
    dataset_xlsx: Path, providers_yaml: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch
) -> None:
    monkeypatch.delenv("ELEVENLABS_API_KEY")  # a dry run must not need a key
    route = respx.post(URL).mock(return_value=httpx.Response(200, content=b"\x00\x00"))
    out = tmp_path / "audio"

    assert run(_args(dataset_xlsx, providers_yaml, out, "--dry-run")) == 0

    shown = capsys.readouterr().out
    assert "BN-PLN-001  6 chars" in shown and "sent:    হ্যাঁ।" in shown
    assert "EXCEEDS max_chars" in shown  # BN-NUM-010 is over the test config's limit
    assert "nothing was sent" in shown
    assert route.call_count == 0 and not out.exists()


def test_dry_run_out_writes_jsonl(
    dataset_xlsx: Path, providers_yaml: Path, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("ELEVENLABS_API_KEY")
    target = tmp_path / "preview" / "dry.jsonl"  # implies --dry-run; parent directory is created

    assert run(_args(dataset_xlsx, providers_yaml, tmp_path / "audio", "--dry-run-out", str(target))) == 0

    rows = [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines()]
    assert [r["item_id"] for r in rows] == ["BN-EDG-001", "BN-NUM-010", "BN-PLN-001", "BN-PLN-002"]
    assert rows[0]["text"] == "র\u200dযাব" and rows[0]["variant"] == "baseline"  # sent byte-for-byte
    assert [r["exceeds_max_chars"] for r in rows] == [False, True, False, False]
    assert not (tmp_path / "audio").exists()


def test_dry_run_emotive_out_has_dataset_and_sent_text(
    providers_yaml: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ELEVENLABS_API_KEY")
    (providers_yaml.parent / "elevenlabs.json").write_text(
        json.dumps({"laugh": "[laughs]"}), encoding="utf-8"
    )
    target = tmp_path / "dry.jsonl"

    dataset = _emotive_dataset(tmp_path)
    args = _args(
        dataset, providers_yaml, tmp_path / "audio", "--variant", "emotive", "--dry-run-out", str(target)
    )
    assert run(args) == 0

    rows = [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines()]
    assert [(r["dataset_text"], r["text"]) for r in rows] == [
        ("[laugh] হ্যাঁ।", "[laughs] হ্যাঁ।"),
        ("[sigh] না। [laugh]", "না। [laughs]"),
    ]
    assert all(r["variant"] == "emotive" and "parts" not in r for r in rows)


def test_dry_run_keeps_dataset_tags_when_the_provider_has_no_tag_map_entries(
    providers_yaml: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """sarvam/openai have empty tag maps: every tag is removed, but dataset_text must still show them."""
    monkeypatch.delenv("ELEVENLABS_API_KEY")
    (providers_yaml.parent / "elevenlabs.json").write_text("{}", encoding="utf-8")
    target = tmp_path / "dry.jsonl"
    args = _args(
        _emotive_dataset(tmp_path), providers_yaml, tmp_path / "audio",
        "--variant", "emotive", "--dry-run-out", str(target),
    )  # fmt: skip

    assert run(args) == 0

    rows = [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines()]
    assert [(r["dataset_text"], r["text"]) for r in rows] == [
        ("[laugh] হ্যাঁ।", "হ্যাঁ।"),
        ("[sigh] না। [laugh]", "না।"),
    ]
