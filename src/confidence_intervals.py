"""
Bootstrap 95% confidence intervals for corpus-level CER/WER, plus paired
bootstrap comparisons between models adjacent in the ranking.

Works offline from the published per-file results -- no API calls, no audio:
it re-normalizes the ref/hyp pairs in results/per_file.csv (and
results/streaming_per_file.csv), so anyone can check whether a gap between
two providers is larger than sampling noise on a 1001-clip test set.

Method: resample the test files with replacement (B times), recompute the
corpus-level rate (total edits / total reference length) on each resample,
and take the 2.5 / 97.5 percentiles. Paired comparisons resample the same
file indices for both models, over the files both of them transcribed.

Produces:
  results/leaderboard_ci.csv            CER/WER with 95% CI per batch model
  results/streaming_leaderboard_ci.csv  same, streaming models
  results/pairwise.csv                  adjacent-rank CER gaps, 95% CI, p(A better)

Usage:  python src/confidence_intervals.py [--iters 10000] [--seed 0]
"""
import argparse
import os
import sys

import jiwer
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from normalize import normalize  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(ROOT, "results")


def edit_counts(ref: str, hyp: str, unit: str):
    """(edits, reference length) at character or word level."""
    if unit == "char":
        out = jiwer.process_characters(ref, hyp)
    else:
        out = jiwer.process_words(ref, hyp)
    edits = out.substitutions + out.deletions + out.insertions
    return edits, out.substitutions + out.deletions + out.hits


def per_file_counts(per_file: pd.DataFrame) -> dict:
    """model -> DataFrame indexed by file_path with char/word edit counts."""
    out = {}
    for model, g in per_file.groupby("model"):
        rows = []
        for fp, ref, hyp in zip(g["file_path"], g["ref"], g["hyp"]):
            r, h = normalize(ref), normalize(hyp)
            if not r.strip():
                continue
            ce, cn = edit_counts(r, h, "char")
            we, wn = edit_counts(r, h, "word")
            rows.append((fp, ce, cn, we, wn))
        out[model] = pd.DataFrame(rows, columns=["file_path", "ce", "cn", "we", "wn"]).set_index("file_path")
    return out


def bootstrap_rate(edits, lens, idx):
    return edits[idx].sum(axis=1) / lens[idx].sum(axis=1)


def leaderboard_ci(counts: dict, iters: int, rng) -> pd.DataFrame:
    rows = []
    for model, df in counts.items():
        n = len(df)
        idx = rng.integers(0, n, size=(iters, n))
        row = {"model": model, "files_scored": n}
        for key, e, l in (("CER", "ce", "cn"), ("WER", "we", "wn")):
            edits, lens = df[e].to_numpy(), df[l].to_numpy()
            boots = bootstrap_rate(edits, lens, idx)
            row[key] = round(edits.sum() / lens.sum(), 4)
            row[f"{key}_ci_low"] = round(float(np.percentile(boots, 2.5)), 4)
            row[f"{key}_ci_high"] = round(float(np.percentile(boots, 97.5)), 4)
        rows.append(row)
    return pd.DataFrame(rows).sort_values("CER").reset_index(drop=True)


def pairwise(counts: dict, ranking: list, iters: int, rng, mode: str) -> list:
    rows = []
    for a, b in zip(ranking, ranking[1:]):
        shared = counts[a].index.intersection(counts[b].index)
        A, B = counts[a].loc[shared], counts[b].loc[shared]
        n = len(shared)
        idx = rng.integers(0, n, size=(iters, n))
        ca = bootstrap_rate(A["ce"].to_numpy(), A["cn"].to_numpy(), idx)
        cb = bootstrap_rate(B["ce"].to_numpy(), B["cn"].to_numpy(), idx)
        diff = cb - ca
        rows.append({
            "mode": mode,
            "model_a": a,
            "model_b": b,
            "shared_files": n,
            "cer_gap_b_minus_a": round(float(B["ce"].sum() / B["cn"].sum() - A["ce"].sum() / A["cn"].sum()), 4),
            "gap_ci_low": round(float(np.percentile(diff, 2.5)), 4),
            "gap_ci_high": round(float(np.percentile(diff, 97.5)), 4),
            "p_a_better": round(float((diff > 0).mean()), 4),
        })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--iters", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    rng = np.random.default_rng(args.seed)

    pair_rows = []
    for mode, src, dst in (("batch", "per_file.csv", "leaderboard_ci.csv"),
                           ("streaming", "streaming_per_file.csv", "streaming_leaderboard_ci.csv")):
        path = os.path.join(RESULTS, src)
        if not os.path.exists(path):
            print(f"skip {mode}: {src} not found")
            continue
        per_file = pd.read_csv(path, keep_default_na=False)
        counts = per_file_counts(per_file)
        lb = leaderboard_ci(counts, args.iters, rng)
        lb.to_csv(os.path.join(RESULTS, dst), index=False)
        print(f"\n== {mode} ==")
        print(lb.to_string(index=False))
        pair_rows += pairwise(counts, list(lb["model"]), args.iters, rng, mode)

    pw = pd.DataFrame(pair_rows)
    pw.to_csv(os.path.join(RESULTS, "pairwise.csv"), index=False)
    print("\n== adjacent-rank CER comparisons (paired bootstrap) ==")
    print(pw.to_string(index=False))
    print(f"\nWrote leaderboard_ci.csv, streaming_leaderboard_ci.csv, pairwise.csv to {RESULTS}/")


if __name__ == "__main__":
    main()
