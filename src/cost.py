"""
Price every benchmarked model from pricing/prices.yaml and the real clip
durations of the test set.

For each model it reports:
  list_usd_per_hour       the provider's published pay-as-you-go rate in USD
                          per hour of audio (token-billed models: converted
                          with the provider's own token-per-hour figures)
  effective_usd_per_hour  what the benchmark clips cost per hour of audio once
                          the provider's billing rules are applied to every
                          request (rounding up to the second, minimum billed
                          length, streaming session time, ...). Short clips
                          cost more than list where providers round or have
                          minimums.
  test_set_cost_usd       estimated cost of transcribing the 1001-clip test set
  cost_type               exact | estimate | minimum -- see pricing/prices.yaml

Every rate in prices.yaml carries its source URL, the quoted page text and
the date it was checked; the URL and date are copied into the output so the
numbers can be audited.

Produces:
  results/cost.csv               batch models
  results/streaming_cost.csv     streaming models

Usage:  python src/cost.py
"""
import math
import os

import pandas as pd
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(ROOT, "results")


def clip_durations() -> pd.Series:
    """file_path -> audio duration in seconds, measured during the streaming run."""
    sp = pd.read_csv(os.path.join(RESULTS, "streaming_per_file.csv"))
    return sp.groupby("file_path")["audio_duration_s"].median()


def billed_seconds(duration_s: float, entry: dict) -> float:
    rounding = entry.get("rounding", "none")
    if rounding == "ceil_second":
        s = math.ceil(duration_s)
    elif rounding == "none":
        s = duration_s
    else:
        raise ValueError(f"unknown rounding {rounding!r}")
    return max(float(s), float(entry.get("min_billed_seconds", 0)))


def to_usd(amount: float, currency: str, fx: dict) -> float:
    return amount if currency == "USD" else amount / fx[currency]


def list_per_hour(entry: dict, fx: dict) -> float:
    cur = entry.get("currency", "USD")
    if entry["billing"] == "duration":
        return to_usd(entry["price_per_hour"], cur, fx)
    per_hour = entry["input_audio_tokens_per_second"] * 3600 / 1e6 * entry["price_per_1m_input_audio_tokens"]
    if "output_tokens_per_hour" in entry:
        per_hour += entry["output_tokens_per_hour"] / 1e6 * entry["price_per_1m_output_tokens"]
    return to_usd(per_hour, cur, fx)


def request_costs(entry: dict, clips: pd.DataFrame, fx: dict) -> float:
    """Total USD for the given clips (columns: audio_s, session_s, hyp)."""
    cur = entry.get("currency", "USD")
    if entry["billing"] == "duration":
        billed = sum(billed_seconds(d, entry) for d in clips["audio_s"])
        return to_usd(billed / 3600 * entry["price_per_hour"], cur, fx)

    if entry["billing"] == "token":
        basis = clips["session_s"] if entry.get("input_basis") == "session" else clips["audio_s"]
        in_tokens = basis.sum() * entry["input_audio_tokens_per_second"]
        cost = in_tokens / 1e6 * entry["price_per_1m_input_audio_tokens"]
        if "output_tokens_per_char" in entry:
            out_tokens = clips["hyp"].str.len().sum() * entry["output_tokens_per_char"]
            cost += out_tokens / 1e6 * entry["price_per_1m_output_tokens"]
        return to_usd(cost, cur, fx)

    raise ValueError(f"unknown billing type {entry['billing']!r}")


def main():
    prices = yaml.safe_load(open(os.path.join(ROOT, "pricing", "prices.yaml"), encoding="utf-8"))
    fx = prices.get("fx_per_usd", {})
    durations = clip_durations()

    for mode, per_file, leaderboard, out in (
        ("batch", "per_file.csv", "leaderboard.csv", "cost.csv"),
        ("streaming", "streaming_per_file.csv", "streaming_leaderboard.csv", "streaming_cost.csv"),
    ):
        pf = pd.read_csv(os.path.join(RESULTS, per_file), keep_default_na=False)
        lb = pd.read_csv(os.path.join(RESULTS, leaderboard)).set_index("model")
        rows = []
        for model in lb.index:
            entry = prices["models"].get(model)
            if entry is None:
                print(f"[{mode}] {model}: no price in pricing/prices.yaml -- skipped")
                continue
            g = pf[pf["model"] == model]
            clips = pd.DataFrame({
                "audio_s": durations.loc[g["file_path"]].to_numpy(),
                "session_s": pd.to_numeric(g["total_latency_s"], errors="coerce").to_numpy()
                             if "total_latency_s" in g else durations.loc[g["file_path"]].to_numpy(),
                "hyp": g["hyp"].astype(str).to_numpy(),
            })
            total = request_costs(entry, clips, fx)
            audio_h = clips["audio_s"].sum() / 3600
            rows.append({
                "model": model,
                "provider": entry["provider"],
                "priced_as": entry["priced_as"],
                "CER": lb.loc[model, "CER"],
                "list_usd_per_hour": round(list_per_hour(entry, fx), 4),
                "effective_usd_per_hour": round(total / audio_h, 4),
                "test_set_cost_usd": round(total, 4),
                "clips_priced": len(clips),
                "cost_type": entry["cost_type"],
                "billing_rules": entry.get("billing_rules", ""),
                "note": entry.get("note", ""),
                "source_url": entry["source_url"],
                "checked": entry["checked"],
            })
        df = pd.DataFrame(rows).sort_values("CER")
        df.to_csv(os.path.join(RESULTS, out), index=False)
        print(f"\n== {mode} ==")
        print(df[["model", "CER", "list_usd_per_hour", "effective_usd_per_hour",
                  "test_set_cost_usd", "cost_type"]].to_string(index=False))

    print(f"\nWrote cost.csv and streaming_cost.csv to {RESULTS}/")


if __name__ == "__main__":
    main()
