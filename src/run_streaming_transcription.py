"""
Run streaming-mode transcription for providers that support it, recording
streaming-specific timing metrics (first partial / first final / tail
latency, RTF, and partial-result stability) for src/score_streaming.py.

Only providers whose `type` is in providers.STREAMING_REGISTRY are eligible
-- currently just `google_stt_streaming`, wired to `google_chirp2_streaming`
in config.yaml. Add more streaming adapters + config blocks to extend
coverage to other providers.

Each file is streamed at real-time pace (chunks are paced to simulate a live
mic feed), so a run over N files takes roughly as long as N files' worth of
audio, not the near-instant wall time of the batch runner.

Usage:
    python src/run_streaming_transcription.py                        # all enabled streaming providers
    python src/run_streaming_transcription.py google_chirp2_streaming
    python src/run_streaming_transcription.py --limit 3              # smoke test: first 3 files

Results are appended to results/raw_streaming/<provider_name>.jsonl.
Already-transcribed files are skipped, so re-running only fills gaps -- a
paid API is never streamed twice for the same clip.
"""
import argparse
import glob
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import yaml

sys.path.insert(0, os.path.dirname(__file__))
import providers  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def to_file_path(disk_path: str, audio_dir: str) -> str:
    """wavs/audio_books/x.wav -> /audio_books/x.wav (the BanSpeech key)."""
    rel = os.path.relpath(disk_path, audio_dir).replace(os.sep, "/")
    return "/" + rel


def load_cache(raw_path: str) -> set:
    done = set()
    if os.path.exists(raw_path):
        with open(raw_path, encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    if not rec.get("error"):
                        done.add(rec["file_path"])
                except json.JSONDecodeError:
                    continue
    return done


def run_provider(name: str, pcfg: dict, wavs: list, audio_dir: str,
                  raw_path: str, concurrency: int):
    fn = providers.get_streaming(pcfg["type"])
    done = load_cache(raw_path)
    todo = [w for w in wavs if to_file_path(w, audio_dir) not in done]
    if not todo:
        print(f"[{name}] all {len(wavs)} files already cached")
        return
    print(f"[{name}] {len(todo)} to do ({len(done)} cached) -- "
          "streamed at real-time pace, this takes roughly as long as the audio itself")

    def work(disk_path):
        fp = to_file_path(disk_path, audio_dir)
        try:
            rec = fn(disk_path, pcfg)
            rec["file_path"] = fp
            rec["error"] = None
            return rec
        except Exception as e:  # capture, keep going
            return {"file_path": fp, "transcript": "", "error": f"{type(e).__name__}: {e}"}

    errors = 0
    completed = 0
    total = len(todo)
    with open(raw_path, "a", encoding="utf-8") as out, \
            ThreadPoolExecutor(max_workers=concurrency) as ex:
        futs = {ex.submit(work, w): w for w in todo}
        for fut in as_completed(futs):
            rec = fut.result()
            if rec["error"]:
                errors += 1
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out.flush()
            completed += 1
            if completed % 5 == 0 or completed == total:
                print(f"[{name}] Progress: {completed}/{total} files done (errors: {errors})")
    if errors:
        print(f"[{name}] finished with {errors} errors (see {raw_path})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("providers", nargs="*", help="provider names (default: all enabled streaming providers)")
    ap.add_argument("--limit", type=int, default=0, help="only first N wavs (smoke test)")
    ap.add_argument("--config", default=os.path.join(ROOT, "streaming-config.yaml"))
    args = ap.parse_args()

    cfg = yaml.safe_load(open(args.config))
    audio_dir = os.path.join(ROOT, cfg["audio_dir"])
    raw_dir = os.path.join(ROOT, cfg["results_dir"], "raw_streaming")
    os.makedirs(raw_dir, exist_ok=True)

    wavs = sorted(glob.glob(os.path.join(audio_dir, "**", "*.wav"), recursive=True))
    if not wavs:
        sys.exit(f"No wavs under {audio_dir}. Build/download the benchmark audio first.")
    if args.limit:
        wavs = wavs[:args.limit]
    print(f"{len(wavs)} wav files")

    streaming_names = [n for n, p in cfg["providers"].items() if p.get("type") in providers.STREAMING_REGISTRY]
    selected = args.providers or [n for n in streaming_names if cfg["providers"][n].get("enabled")]
    if not selected:
        sys.exit("No streaming-capable providers enabled in config.yaml "
                  f"(type must be one of {sorted(providers.STREAMING_REGISTRY)}).")

    for name in selected:
        pcfg = cfg["providers"][name]
        if pcfg.get("type") not in providers.STREAMING_REGISTRY:
            print(f"[{name}] SKIP -- type '{pcfg.get('type')}' has no streaming adapter")
            continue
        missing = [pcfg[k] for k in ("api_key_env", "project_env")
                   if pcfg.get(k) and pcfg[k] not in os.environ]
        if missing:
            print(f"[{name}] SKIP -- ${', $'.join(missing)} not set")
            continue
        raw_path = os.path.join(raw_dir, f"{name}.jsonl")
        run_provider(name, pcfg, wavs, audio_dir, raw_path, cfg.get("streaming_concurrency", 1))


if __name__ == "__main__":
    main()
