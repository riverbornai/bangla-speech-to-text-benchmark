"""
Builds the two Hugging Face releases from the files in results/:

  hf/dist/results/      -> dataset repo  riverborn/bangla-stt-benchmark-results
  hf/dist/leaderboard/  -> Space         riverborn/bangla-stt-leaderboard

The release holds no audio and no BanSpeech reference text. BanSpeech is
CC-BY-NC-4.0, so users get the audio and the references from BanSpeech and
join on `file_path`.

Requirements:  pip install pandas pyarrow
Run:           python hf/build_hf_release.py
"""
import json
import os
import shutil

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(ROOT, "results")
HF = os.path.join(ROOT, "hf")
DIST = os.path.join(HF, "dist")

TESTED = "September 2026"
PRICES_CHECKED = "2026-09-24"

# Benchmark run ID -> what users see.
MODELS = {
    # batch
    "sarvam_saarika": ("Sarvam AI", "saarika:v2.5"),
    "soniox": ("Soniox", "stt-async-v5"),
    "deepgram_nova3": ("Deepgram", "nova-3"),
    "gemini_25_flash": ("Google Gemini", "gemini-2.5-flash"),
    "elevenlabs_scribe": ("ElevenLabs", "scribe_v1"),
    "google_chirp2": ("Google Cloud", "chirp_2"),
    "openai_4o": ("OpenAI", "gpt-4o-transcribe"),
    "groq_whisper": ("Groq", "whisper-large-v3"),
    # streaming
    "soniox_rt_streaming": ("Soniox", "stt-rt-v5"),
    "sarvam_saaras_realtime_streaming": ("Sarvam AI", "saaras:v3-realtime"),
    "deepgram_nova3_streaming": ("Deepgram", "nova-3"),
    "google_chirp2_streaming": ("Google Cloud", "chirp_2"),
    "openai_4o_streaming": ("OpenAI", "gpt-4o-transcribe (Realtime API)"),
    "elevenlabs_scribe_streaming": ("ElevenLabs", "scribe_v2_realtime"),
    "gemini_25_flash_streaming": (
        "Google Gemini",
        "gemini-2.5-flash-native-audio-preview-12-2025 (Live API)",
    ),
}

DOMAINS = {
    "audio_books": "Audiobooks",
    "biography": "Biography",
    "celebrity_interview": "Celebrity interview",
    "class_lecture": "Class lecture",
    "documentary": "Documentary",
    "drama_series": "Drama series",
    "kid_cartoon": "Kids' cartoon",
    "kid_voice": "Kids' voices",
    "medicine": "Medicine",
    "parliament_speech": "Parliament",
    "political_talkshow": "Political talk show",
    "sports": "Sports",
    "television_news": "TV news",
}


def read(name):
    return pd.read_csv(os.path.join(RESULTS, name))


def add_names(df, col="model"):
    unknown = set(df[col]) - set(MODELS)
    if unknown:
        raise SystemExit(f"Add these run IDs to MODELS: {sorted(unknown)}")
    df.insert(1, "provider", df[col].map(lambda m: MODELS[m][0]))
    df.insert(2, "model_id", df[col].map(lambda m: MODELS[m][1]))
    return df.rename(columns={col: "run_id"})


def domain_from_path(path):
    return path.strip("/").split("/")[0]


def build_leaderboard(mode):
    prefix = "" if mode == "batch" else "streaming_"
    board = read(f"{prefix}leaderboard.csv")
    ci = read(f"{prefix}leaderboard_ci.csv")[
        ["model", "CER_ci_low", "CER_ci_high", "WER_ci_low", "WER_ci_high"]
    ]
    cost = read(f"{prefix}cost.csv")[
        ["model", "list_usd_per_hour", "effective_usd_per_hour", "test_set_cost_usd", "cost_type"]
    ]
    df = board.merge(ci, on="model", how="left").merge(cost, on="model", how="left")
    df = df.sort_values("CER").reset_index(drop=True)
    df.insert(0, "rank", df.index + 1)
    df = add_names(df)
    df.columns = [c.lower() for c in df.columns]
    df.insert(1, "mode", mode)
    return df


def build_by_domain():
    frames = []
    for mode, name in [("batch", "by_domain.csv"), ("streaming", "streaming_by_domain.csv")]:
        wide = read(name)
        long = wide.melt(id_vars="model", var_name="domain", value_name="cer")
        long.insert(0, "mode", mode)
        frames.append(long)
    df = pd.concat(frames, ignore_index=True)
    df = add_names(df)
    df["domain_label"] = df["domain"].map(DOMAINS)
    return df


def build_predictions(name, mode):
    df = read(name).drop(columns=["ref"])  # BanSpeech text stays at BanSpeech
    df = add_names(df).rename(columns={"hyp": "hypothesis"})
    df.insert(1, "mode", mode)
    return df


def build_pairwise():
    df = read("pairwise.csv")
    for side in ("a", "b"):
        col = f"model_{side}"
        df[f"provider_{side}"] = df[col].map(lambda m: MODELS[m][0])
        df[f"model_id_{side}"] = df[col].map(lambda m: MODELS[m][1])
        df = df.rename(columns={col: f"run_id_{side}"})
    return df


def build_clips():
    test_set = pd.read_csv(os.path.join(ROOT, "data", "test_set.csv"), usecols=["file_path", "domain"])
    return test_set


def write_dataset(tables):
    out = os.path.join(DIST, "results")
    data_dir = os.path.join(out, "data")
    os.makedirs(data_dir, exist_ok=True)
    for name, df in tables.items():
        df.to_parquet(os.path.join(data_dir, f"{name}.parquet"), index=False)
        print(f"  {name}.parquet  {len(df):>5} rows")
    shutil.copy(os.path.join(HF, "templates", "dataset_card.md"), os.path.join(out, "README.md"))
    shutil.copy(os.path.join(RESULTS, "..", "pricing", "prices.yaml"), os.path.join(out, "prices.yaml"))


def round_records(df, cols):
    keep = df[cols].copy()
    return json.loads(keep.round(4).to_json(orient="records"))


def write_space(tables):
    out = os.path.join(DIST, "leaderboard")
    os.makedirs(out, exist_ok=True)
    data = {
        "tested": TESTED,
        "prices_checked": PRICES_CHECKED,
        "clips": int(len(tables["clips"])),
        "domains": DOMAINS,
        "batch": round_records(
            tables["leaderboard_batch"],
            ["rank", "provider", "model_id", "cer", "cer_ci_low", "cer_ci_high", "wer",
             "mean_latency_s", "rtfp50", "list_usd_per_hour", "effective_usd_per_hour",
             "cost_type", "coverage"],
        ),
        "streaming": round_records(
            tables["leaderboard_streaming"],
            ["rank", "provider", "model_id", "cer", "cer_ci_low", "cer_ci_high", "wer",
             "first_partial_p50_s", "first_partial_p95_s", "first_final_p50_s",
             "first_final_p95_s", "finalization_p50_s", "finalization_p95_s",
             "total_latency_mean_s", "list_usd_per_hour", "effective_usd_per_hour",
             "cost_type", "coverage"],
        ),
        "pairwise": round_records(
            tables["pairwise"],
            ["mode", "provider_a", "model_id_a", "provider_b", "model_id_b", "shared_files",
             "cer_gap_b_minus_a", "gap_ci_low", "gap_ci_high", "p_a_better"],
        ),
        "by_domain": round_records(
            tables["by_domain"], ["mode", "provider", "model_id", "domain", "cer"]
        ),
    }
    with open(os.path.join(HF, "templates", "leaderboard.html"), encoding="utf-8") as f:
        page = f.read()
    page = page.replace("__BENCHMARK_DATA__", json.dumps(data, ensure_ascii=False))
    with open(os.path.join(out, "index.html"), "w", encoding="utf-8") as f:
        f.write(page)
    shutil.copy(os.path.join(HF, "templates", "space_readme.md"), os.path.join(out, "README.md"))
    print(f"  leaderboard/index.html  {os.path.getsize(os.path.join(out, 'index.html')) // 1024} KB")


def main():
    shutil.rmtree(DIST, ignore_errors=True)
    tables = {
        "clips": build_clips(),
        "leaderboard_batch": build_leaderboard("batch"),
        "leaderboard_streaming": build_leaderboard("streaming"),
        "by_domain": build_by_domain(),
        "batch_predictions": build_predictions("per_file.csv", "batch"),
        "streaming_predictions": build_predictions("streaming_per_file.csv", "streaming"),
        "pairwise": build_pairwise(),
    }
    print("Dataset repo:")
    write_dataset(tables)
    print("Space:")
    write_space(tables)
    print(f"Done. Output is in {os.path.relpath(DIST, ROOT)}/")


if __name__ == "__main__":
    main()
