"""
Smoke test: run ONE audio file through each provider to validate that the
adapter works and the API key is valid -- before committing to a full run.

For every enabled provider it reports one of:
    OK     transcript returned (with latency, char count, and CER if the file
           has a ground-truth reference)
    FAIL   the API call raised (bad key, wrong endpoint, unsupported language...)
    SKIP   the provider's API key env var is not set

Usage:
    python src/smoke_test.py                         # first wav, all keyed providers
    python src/smoke_test.py --file /audio_books/book_10_d_164.wav
    python src/smoke_test.py --file wavs/sports/sports_113_d_18.wav
    python src/smoke_test.py --provider sarvam_saarika gemini_25_flash
"""
import argparse
import glob
import os
import sys
import time

import yaml

sys.path.insert(0, os.path.dirname(__file__))
import providers                       # noqa: E402
from normalize import normalize        # noqa: E402
from references import load_references  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resolve_file(arg: str, audio_dir: str) -> str:
    """Accept a disk path, a BanSpeech file_path (/domain/x.wav), or None."""
    if arg:
        if os.path.isfile(arg):
            return arg
        cand = os.path.join(audio_dir, arg.lstrip("/"))
        if os.path.isfile(cand):
            return cand
        sys.exit(f"File not found: {arg}")
    wavs = sorted(glob.glob(os.path.join(audio_dir, "**", "*.wav"), recursive=True))
    if not wavs:
        sys.exit(f"No wavs under {audio_dir}. Run download_benchmark_audio.py first.")
    return wavs[0]


def to_file_path(disk_path: str, audio_dir: str) -> str:
    rel = os.path.relpath(disk_path, audio_dir).replace(os.sep, "/")
    return "/" + rel


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default="", help="disk path or /domain/name.wav")
    ap.add_argument("--provider", nargs="*", help="provider names (default: all enabled)")
    ap.add_argument("--config", default=os.path.join(ROOT, "config.yaml"))
    args = ap.parse_args()

    cfg = yaml.safe_load(open(args.config))
    audio_dir = os.path.join(ROOT, cfg["audio_dir"])
    wav = resolve_file(args.file, audio_dir)
    fp = to_file_path(wav, audio_dir)

    # Ground-truth reference for this file, if we have it.
    ref = None
    try:
        refs = load_references(os.path.join(ROOT, cfg["test_set"]))
        if fp in refs:
            ref = refs[fp]["ref"]
    except Exception:
        pass

    import jiwer  # only needed if we have a reference

    print(f"File : {fp}")
    print(f"Size : {os.path.getsize(wav) / 1024:.0f} KB")
    if ref:
        print(f"Ref  : {ref[:80]}")
    print("-" * 72)

    selected = args.provider or [n for n, p in cfg["providers"].items() if p.get("enabled")]
    results = []
    for name in selected:
        pcfg = cfg["providers"][name]
        missing = [pcfg[k] for k in ("api_key_env", "project_env")
                   if pcfg.get(k) and pcfg[k] not in os.environ]
        if missing:
            print(f"SKIP  {name:20} (${', $'.join(missing)} not set)")
            results.append((name, "SKIP"))
            continue

        fn = providers.get(pcfg["type"])
        t0 = time.time()
        try:
            text = fn(wav, pcfg)
            dt = time.time() - t0
            cer = ""
            if ref and text.strip():
                cer = f"  CER={jiwer.cer(normalize(ref), normalize(text)):.3f}"
            print(f"OK    {name:20} {dt:5.1f}s  {len(text):4d} chars{cer}")
            print(f"        {text[:90]}")
            results.append((name, "OK"))
        except Exception as e:
            dt = time.time() - t0
            print(f"FAIL  {name:20} {dt:5.1f}s  {type(e).__name__}: {str(e)[:120]}")
            results.append((name, "FAIL"))

    print("-" * 72)
    ok = sum(s == "OK" for _, s in results)
    fail = sum(s == "FAIL" for _, s in results)
    skip = sum(s == "SKIP" for _, s in results)
    print(f"Summary: {ok} OK, {fail} FAIL, {skip} SKIP")
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
