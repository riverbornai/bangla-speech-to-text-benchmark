"""
Score cached transcripts against ground truth.

Produces:
  results/leaderboard.csv   overall CER/WER + coverage + mean latency per model
  results/by_domain.csv     CER per model x domain (the interesting heatmap)
  results/per_file.csv      every file x model CER/WER (for error inspection)
  results/report.md         human-readable summary

CER is the primary metric for Bangla (robust to word-spacing differences);
WER is reported alongside. Aggregates are corpus-level (total edits / total
reference length), not the mean of per-file rates.

Usage:  python src/score.py
"""
import glob
import json
import os
import sys
import numpy as np
import jiwer
import pandas as pd
import yaml

sys.path.insert(0, os.path.dirname(__file__))
from normalize import normalize          # noqa: E402
from references import load_references   # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_raw(raw_path: str) -> dict:
    out = {}
    with open(raw_path, encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not rec.get("error"):
                out[rec["file_path"]] = rec
    return out


def corpus_rate(metric_fn, refs, hyps):
    """corpus-level CER/WER over aligned lists; empty -> None."""
    pairs = [(r, h) for r, h in zip(refs, hyps) if r.strip()]
    if not pairs:
        return None
    r, h = zip(*pairs)
    return metric_fn(list(r), list(h))


def main():
    cfg = yaml.safe_load(open(os.path.join(ROOT, "config.yaml")))
    refs = load_references(os.path.join(ROOT, cfg["test_set"]))
    raw_dir = os.path.join(ROOT, cfg["results_dir"], "raw")
    results_dir = os.path.join(ROOT, cfg["results_dir"])

    raw_files = sorted(glob.glob(os.path.join(raw_dir, "*.jsonl")))
    if not raw_files:
        sys.exit(f"No transcripts in {raw_dir}. Run run_transcription.py first.")

    per_file_rows = []
    leaderboard = []
    domain_cer = {}  # model -> domain -> (refs, hyps)

    for rp in raw_files:
        model = os.path.splitext(os.path.basename(rp))[0]
        data = load_raw(rp)
        refs_n, hyps_n, latencies, rtfs =[], [], [], []
        domain_cer[model] = {}

        for fp, meta in refs.items():
            domain = meta["domain"]
            ref_n = normalize(meta["ref"])
            rec = data.get(fp)
            if rec is None:
                continue  # not transcribed by this model
            hyp_n = normalize(rec["transcript"])
            refs_n.append(ref_n)
            hyps_n.append(hyp_n)
            latencies.append(rec.get("latency_s", 0) or 0)
            rtfs.append(rec.get("rtf"))
            file_cer = jiwer.cer(ref_n, hyp_n) if ref_n.strip() else None
            file_wer = jiwer.wer(ref_n, hyp_n) if ref_n.strip() else None
            per_file_rows.append({
                "model": model, "file_path": fp, "domain": domain,
                "cer": file_cer, "wer": file_wer,
                "ref": meta["ref"], "hyp": rec["transcript"],
            })
            domain_cer[model].setdefault(domain, ([], []))
            domain_cer[model][domain][0].append(ref_n)
            domain_cer[model][domain][1].append(hyp_n)

        leaderboard.append({
            "model": model,
            "files_scored": len(refs_n),
            "coverage": round(len(refs_n) / max(len(refs), 1), 3),
            "CER": corpus_rate(jiwer.cer, refs_n, hyps_n),
            "WER": corpus_rate(jiwer.wer, refs_n, hyps_n),
            "mean_latency_s": round(sum(latencies) / len(latencies), 2) if latencies else None,

            "rtfp50": np.percentile(rtfs, 50) if rtfs else None,   # median — typical case
            "rtfp95": np.percentile(rtfs, 95) if rtfs else None,
        })

    # ---- leaderboard ----
    lb = pd.DataFrame(leaderboard).sort_values("CER", na_position="last")
    for c in ("CER", "WER"):
        lb[c] = lb[c].apply(lambda x: round(x, 4) if x is not None else None)
    lb.to_csv(os.path.join(results_dir, "leaderboard.csv"), index=False)

    # ---- per-domain CER matrix ----
    domains = sorted({m["domain"] for m in refs.values()})
    dom_rows = []
    for model, dmap in domain_cer.items():
        row = {"model": model}
        for d in domains:
            if d in dmap:
                r, h = dmap[d]
                row[d] = round(jiwer.cer(r, h), 4)
            else:
                row[d] = None
        dom_rows.append(row)
    by_domain = pd.DataFrame(dom_rows).set_index("model")
    by_domain.to_csv(os.path.join(results_dir, "by_domain.csv"))

    # ---- per-file detail ----
    pf = pd.DataFrame(per_file_rows)
    pf.to_csv(os.path.join(results_dir, "per_file.csv"), index=False)

    # ---- markdown report ----
    md = ["# Bangla ASR Benchmark Results\n",
          f"Test set: {len(refs)} utterances across {len(domains)} domains "
          "(BanSpeech). Metric: **CER** (primary), WER (secondary), "
          "corpus-level after shared Bangla normalization.\n",
          "## Leaderboard (lower is better)\n",
          lb.to_markdown(index=False),
          "\n## CER by domain\n",
          by_domain.to_markdown()]
    with open(os.path.join(results_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md))

    print(lb.to_string(index=False))
    print(f"\nWrote leaderboard.csv, by_domain.csv, per_file.csv, report.md to {results_dir}/")


if __name__ == "__main__":
    main()
