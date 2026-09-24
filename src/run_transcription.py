"""
Run every enabled provider over the downloaded wavs and cache raw transcripts.

Usage:
    python src/run_transcription.py                 # all enabled providers
    python src/run_transcription.py sarvam_saarika  # one provider by name
    python src/run_transcription.py --limit 3       # smoke test: first 3 files

Results are appended to results/raw/<provider_name>.jsonl. Already-transcribed
files are skipped, so re-running only fills gaps -- a paid API is never
called twice for the same clip.
"""
import argparse
import glob
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np 
import yaml
from tqdm import tqdm
import wave

    
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
    fn = providers.get(pcfg["type"])
    done = load_cache(raw_path)
    todo = [w for w in wavs if to_file_path(w, audio_dir) not in done]
    if not todo:
        print(f"[{name}] all {len(wavs)} files already cached")
        return
    print(f"[{name}] {len(todo)} to do ({len(done)} cached)")

    def work(disk_path):
        fp = to_file_path(disk_path, audio_dir)

        def get_audio_duration(wav_path: str) -> float:
            with wave.open(wav_path, "r") as w:
                return w.getnframes() / w.getframerate()
        audio_dur = get_audio_duration(disk_path)
        t0 =time.perf_counter()
        try:
            text = fn(disk_path, pcfg)
            latency = time.perf_counter() - t0
            return {"file_path": fp, "transcript": text,
                    "latency_s": round(latency, 2), 
                    "audio_duration_s": round(audio_dur, 3),
                    "rtf": round(latency / audio_dur, 4),
                    "error": None}
        except Exception as e:  # capture, keep going
            return {"file_path": fp, "transcript": "",
                    "latency_s": round(time.perf_counter() - t0, 2),
                    "error": f"{type(e).__name__}: {e}"}

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
    ap.add_argument("providers", nargs="*", help="provider names (default: all enabled)")
    ap.add_argument("--limit", type=int, default=0, help="only first N wavs (smoke test)")
    ap.add_argument("--config", default=os.path.join(ROOT, "config.yaml"))
    args = ap.parse_args()

    cfg = yaml.safe_load(open(args.config))
    audio_dir = os.path.join(ROOT, cfg["audio_dir"])
    raw_dir = os.path.join(ROOT, cfg["results_dir"], "raw")
    os.makedirs(raw_dir, exist_ok=True)

    wavs = sorted(glob.glob(os.path.join(audio_dir, "**", "*.wav"), recursive=True))
    if not wavs:
        sys.exit(f"No wavs under {audio_dir}. Run download_benchmark_audio.py first.")
    if args.limit:
        wavs = wavs[:args.limit]
    print(f"{len(wavs)} wav files")

    selected = args.providers or [n for n, p in cfg["providers"].items() if p.get("enabled")]
    
    with ThreadPoolExecutor(max_workers=len(selected)) as pe:
        futures = {}
        for name in selected:
            
            pcfg = cfg["providers"][name]
            if not pcfg.get("enabled") and name not in args.providers:
                continue
            if pcfg.get("type") not in providers.REGISTRY:
                print(f"[{name}] SKIP -- type '{pcfg.get('type')}' is streaming-only "
                      "(use run_streaming_transcription.py)")
                continue
            missing = [pcfg[k] for k in ("api_key_env", "project_env")
                       if pcfg.get(k) and pcfg[k] not in os.environ]
            if missing:
                print(f"[{name}] SKIP -- ${', $'.join(missing)} not set")
                continue
            raw_path = os.path.join(raw_dir, f"{name}.jsonl")
            
            fut = pe.submit(run_provider, name, pcfg, wavs, audio_dir, raw_path, cfg.get("concurrency", 4))
            futures[fut] = name
            
        for fut in as_completed(futures):
            name = futures[fut]
            try:
                fut.result()
            except Exception as e:
                print(f"[{name}] Failed with exception: {e}")


if __name__ == "__main__":
    main()
