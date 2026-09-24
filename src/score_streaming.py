"""
Score streaming-mode transcripts against ground truth and summarize
streaming-specific latency/stability metrics.

Produces:
  results/streaming_leaderboard.csv   CER/WER + latency percentiles + stability per model
  results/streaming_by_domain.csv     CER per model x domain
  results/streaming_per_file.csv      every file x model, timing + CER/WER
  results/streaming_report.md         human-readable summary

Metrics (beyond the batch CER/WER, computed identically on the final
transcript so streaming and batch numbers stay comparable):
  first_partial_latency_s   time to the first interim hypothesis -- perceived responsiveness
  first_final_latency_s     time to the first finalized segment
  finalization_latency_s    total_latency_s - audio_duration_s: the "tail" delay a user
                             feels after they stop talking, before the final transcript lands
  total_latency_s           wall-clock time for the whole streamed session
  rtf                       total_latency_s / audio_duration_s; must stay < 1 to keep up with
                             a live feed
  num_partial_results       count of interim updates emitted (0 if the provider only finalizes)
  num_final_results         count of finalized segments
  partial_stability_cer     mean CER of every interim hypothesis against ground truth --
                             low = partials converge to the right text early and are safe to
                             show the user before finalization; high = partials are unreliable

Usage:  python src/score_streaming.py
        python src/score_streaming.py --config path/to/streaming-config.yaml
"""
import argparse
import glob
import json
import os
import sys

import jiwer
import numpy as np
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


def pct(values, q):
    vals = [v for v in values if v is not None]
    return round(float(np.percentile(vals, q)), 3) if vals else None


def mean(values):
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals), 3) if vals else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(ROOT, "streaming-config.yaml"))
    args = ap.parse_args()

    cfg = yaml.safe_load(open(args.config))
    refs = load_references(os.path.join(ROOT, cfg["test_set"]))
    raw_dir = os.path.join(ROOT, cfg["results_dir"], "raw_streaming")
    results_dir = os.path.join(ROOT, cfg["results_dir"])

    raw_files = sorted(glob.glob(os.path.join(raw_dir, "*.jsonl")))
    if not raw_files:
        sys.exit(f"No streaming transcripts in {raw_dir}. Run run_streaming_transcription.py first.")

    per_file_rows = []
    leaderboard = []
    domain_cer = {}  # model -> domain -> (refs, hyps)

    for rp in raw_files:
        model = os.path.splitext(os.path.basename(rp))[0]
        data = load_raw(rp)
        refs_n, hyps_n = [], []
        first_partial, first_final, finalization, total_latency, rtfs = [], [], [], [], []
        partial_stability_cers = []
        domain_cer[model] = {}

        for fp, meta in refs.items():
            rec = data.get(fp)
            if rec is None:
                continue  # not streamed by this model
            domain = meta["domain"]
            ref_n = normalize(meta["ref"])
            hyp_n = normalize(rec.get("transcript", ""))
            refs_n.append(ref_n)
            hyps_n.append(hyp_n)

            first_partial.append(rec.get("first_partial_latency_s"))
            first_final.append(rec.get("first_final_latency_s"))
            finalization.append(rec.get("finalization_latency_s"))
            total_latency.append(rec.get("total_latency_s"))
            rtfs.append(rec.get("rtf"))

            if ref_n.strip():
                for p in rec.get("partial_transcripts", []):
                    partial_stability_cers.append(jiwer.cer(ref_n, normalize(p.get("transcript", ""))))

            file_cer = jiwer.cer(ref_n, hyp_n) if ref_n.strip() else None
            file_wer = jiwer.wer(ref_n, hyp_n) if ref_n.strip() else None
            per_file_rows.append({
                "model": model, "file_path": fp, "domain": domain,
                "cer": file_cer, "wer": file_wer,
                "first_partial_latency_s": rec.get("first_partial_latency_s"),
                "first_final_latency_s": rec.get("first_final_latency_s"),
                "finalization_latency_s": rec.get("finalization_latency_s"),
                "total_latency_s": rec.get("total_latency_s"),
                "audio_duration_s": rec.get("audio_duration_s"),
                "rtf": rec.get("rtf"),
                "num_partial_results": rec.get("num_partial_results"),
                "num_final_results": rec.get("num_final_results"),
                "ref": meta["ref"], "hyp": rec.get("transcript", ""),
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
            "first_partial_p50_s": pct(first_partial, 50),
            "first_partial_p95_s": pct(first_partial, 95),
            "first_final_p50_s": pct(first_final, 50),
            "first_final_p95_s": pct(first_final, 95),
            "finalization_p50_s": pct(finalization, 50),
            "finalization_p95_s": pct(finalization, 95),
            "total_latency_mean_s": mean(total_latency),
            "rtfp50": pct(rtfs, 50),
            "rtfp95": pct(rtfs, 95),
            "partial_stability_cer": mean(partial_stability_cers),
        })

    # ---- leaderboard ----
    lb = pd.DataFrame(leaderboard).sort_values("CER", na_position="last")
    for c in ("CER", "WER"):
        lb[c] = lb[c].apply(lambda x: round(x, 4) if x is not None else None)
    lb.to_csv(os.path.join(results_dir, "streaming_leaderboard.csv"), index=False)

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
    by_domain.to_csv(os.path.join(results_dir, "streaming_by_domain.csv"))

    # ---- per-file detail ----
    pf = pd.DataFrame(per_file_rows)
    pf.to_csv(os.path.join(results_dir, "streaming_per_file.csv"), index=False)

    # ---- markdown report ----
    md = ["# Bangla ASR Streaming Benchmark Results\n",
          f"Test set: {len(refs)} utterances across {len(domains)} domains "
          "(BanSpeech), streamed at simulated real-time pace. Metric: **CER** "
          "(primary), WER (secondary), plus streaming latency percentiles and "
          "partial-result stability (see src/score_streaming.py docstring for "
          "metric definitions).\n",
          "## Leaderboard (lower is better)\n",
          lb.to_markdown(index=False),
          "\n## CER by domain\n",
          by_domain.to_markdown()]
    with open(os.path.join(results_dir, "streaming_report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md))

    print(lb.to_string(index=False))
    print(f"\nWrote streaming_leaderboard.csv, streaming_by_domain.csv, "
          f"streaming_per_file.csv, streaming_report.md to {results_dir}/")


if __name__ == "__main__":
    main()
