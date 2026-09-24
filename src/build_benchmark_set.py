"""
Build a stratified Bangla ASR benchmark set from the local BanSpeech dump.

Samples N utterances (default 100) from each of the 14 BanSpeech domains --
the 13 flat domains plus `dialectal_domains`, whose 7 regional sub-csvs
(barisal, chittagong, dhaka, mymensingh, noakhali, rajshahi, sylhet) are
pooled and sampled as a single domain -- copies the wavs into a fresh
`wavs_<total>/<domain>/` folder, and writes an xlsx test-set spreadsheet in
the same shape src/references.py and src/score.py expect.

Usage:
    python src/build_benchmark_set.py                  # 100/domain -> wavs_1400/, bengali_asr_benchmark_1400.xlsx
    python src/build_benchmark_set.py --per-domain 50   # 50/domain -> wavs_700/, bengali_asr_benchmark_700.xlsx
    python src/build_benchmark_set.py --seed 42          # reproducible sample
"""
import argparse
import csv
import glob
import os
import random
import shutil

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BANSPEECH = os.path.join(ROOT, "banspeech")

FLAT_DOMAINS = [
    "audio_books", "biography", "celebrity_interview", "class_lecture",
    "documentary", "drama_series", "kid_cartoon", "kid_voice", "medicine",
    "parliament_speech", "political_talkshow", "sports", "television_news",
]
DIALECT_DOMAIN = "dialectal_domains"

SPEECH_STYLE = {
    "audio_books": "Studio-quality narration, clean single-speaker read speech",
    "biography": "Studio narration, formal register",
    "celebrity_interview": "TV studio interview mic, spontaneous conversational speech",
    "class_lecture": "Classroom ambient recording, technical/code-switched vocabulary",
    "documentary": "TV documentary narration/voice-over",
    "drama_series": "TV drama audio, emotional/expressive multi-talker speech",
    "kid_cartoon": "Dubbed cartoon voice, kids' register, multi-character",
    "kid_voice": "Natural child speech, informal home setting",
    "medicine": "Lecture-hall recording, heavy English code-switching",
    "parliament_speech": "Large-hall floor mic, formal oratory, background murmur",
    "political_talkshow": "TV panel talk show, overlapping/spontaneous speech",
    "sports": "Sports commentary, fast speech, code-switching",
    "television_news": "Broadcast news studio mic, formal register",
    "dialectal_domains": "Regional dialect speech pooled across Barisal, Chittagong, "
                          "Dhaka, Mymensingh, Noakhali, Rajshahi and Sylhet",
}


def load_flat_domain(domain: str) -> pd.DataFrame:
    df = pd.read_csv(os.path.join(BANSPEECH, f"{domain}.csv"))
    df["domain"] = domain
    return df


def read_dialect_csv(path: str) -> pd.DataFrame:
    """A few dialect csvs have rows double-quoted around the whole line
    (wav path + escaped text), which the csv module parses as a single
    one-element row instead of two columns. Recover wav/text manually."""
    rows = []
    with open(path, encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader)  # header
        for row in reader:
            if len(row) == 2:
                wav, text = row
            else:
                s = row[0]
                comma = s.index(",")
                wav = s[:comma]
                text = s[comma + 1:]
                if text.startswith('"') and text.endswith('"'):
                    text = text[1:-1]
            rows.append({"wav": wav, "text": text})
    return pd.DataFrame(rows)


def load_dialect_domain() -> pd.DataFrame:
    csvs = sorted(glob.glob(os.path.join(BANSPEECH, DIALECT_DOMAIN, "*.csv")))
    dfs = [read_dialect_csv(c) for c in csvs]
    df = pd.concat(dfs, ignore_index=True)
    df["domain"] = DIALECT_DOMAIN
    return df


def resolve_disk_path(domain: str, wav_rel: str) -> str:
    """wav_rel like './drama_series/x.wav' or './dialect_barisal/x.wav'."""
    rel = wav_rel.lstrip("./")
    if domain == DIALECT_DOMAIN:
        direct = os.path.join(BANSPEECH, DIALECT_DOMAIN, *rel.split("/")[-2:])
        if os.path.exists(direct):
            return direct
        # folder-name typo in some dialect csvs (e.g. dialect_barisal.csv vs.
        # the dialect_barishal/ directory on disk) -- fall back to basename search.
        basename = os.path.basename(rel)
        hits = glob.glob(os.path.join(BANSPEECH, DIALECT_DOMAIN, "*", basename))
        if hits:
            return hits[0]
        raise FileNotFoundError(f"{domain}: cannot resolve {wav_rel}")
    return os.path.join(BANSPEECH, domain, os.path.basename(rel))


def sample_domain(domain: str, per_domain: int, rng: random.Random) -> pd.DataFrame:
    df = load_dialect_domain() if domain == DIALECT_DOMAIN else load_flat_domain(domain)
    n = min(per_domain, len(df))
    idx = rng.sample(range(len(df)), n)
    return df.iloc[idx].reset_index(drop=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-domain", type=int, default=100, help="samples per domain (default 100)")
    ap.add_argument("--seed", type=int, default=None, help="random seed (default: fully random each run)")
    ap.add_argument("--skip-dialects", action="store_true",
                     help="exclude dialectal_domains, sampling only the 13 flat domains")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    domains = FLAT_DOMAINS if args.skip_dialects else FLAT_DOMAINS + [DIALECT_DOMAIN]
    total = args.per_domain * len(domains)

    wavs_dir = os.path.join(ROOT, f"wavs_{total}")
    xlsx_path = os.path.join(ROOT, f"bengali_asr_benchmark_{total}.xlsx")
    csv_path = os.path.join(ROOT, "data", f"test_set_{total}.csv")

    if os.path.exists(wavs_dir):
        shutil.rmtree(wavs_dir)
    os.makedirs(wavs_dir)

    rows = []
    domain_summary = []
    sample_id = 1

    for domain in domains:
        src_total = len(load_dialect_domain()) if domain == DIALECT_DOMAIN else len(load_flat_domain(domain))
        picked = sample_domain(domain, args.per_domain, rng)
        out_dir = os.path.join(wavs_dir, domain)
        os.makedirs(out_dir, exist_ok=True)

        for _, row in picked.iterrows():
            disk_path = resolve_disk_path(domain, row["wav"])
            filename = os.path.basename(disk_path)
            shutil.copy2(disk_path, os.path.join(out_dir, filename))

            ref = str(row["text"]).strip()
            rows.append({
                "sample_id": sample_id,
                "domain": domain,
                "filename": filename,
                "file_path": f"/{domain}/{filename}",
                "ground_truth_transcription_bn": ref,
                "char_count": len(ref),
                "model_1_transcript": None, "model_2_transcript": None,
                "model_3_transcript": None, "model_4_transcript": None,
                "wer_model_1": None, "wer_model_2": None,
                "wer_model_3": None, "wer_model_4": None,
                "notes": None,
            })
            sample_id += 1

        domain_summary.append({
            "domain": domain,
            "samples_selected": len(picked),
            "domain_total_in_banspeech": src_total,
            "speech_style / mic-condition proxy": SPEECH_STYLE[domain],
        })
        print(f"[{domain}] {len(picked)} samples -> {out_dir}")

    test_set = pd.DataFrame(rows)
    domain_df = pd.DataFrame(domain_summary)
    domain_df = pd.concat([domain_df, pd.DataFrame([{
        "domain": "TOTAL",
        "samples_selected": domain_df["samples_selected"].sum(),
        "domain_total_in_banspeech": domain_df["domain_total_in_banspeech"].sum(),
        "speech_style / mic-condition proxy": None,
    }])], ignore_index=True)

    readme_rows = [
        ("Bengali ASR Benchmark — {}-Sample Test Set".format(total), None),
        (None, None),
        ("Source dataset", "BanSpeech (SUST-CSE-Speech/banspeech on Hugging Face) -- "
                            "CC BY-NC 4.0, human-annotated multi-domain Bangla ASR benchmark"),
        ("Selection method", f"Random sample of {args.per_domain} utterances per domain, "
                              f"across all 14 BanSpeech domains ({total} total). The "
                              "`dialectal_domains` domain pools 7 regional sub-dialects "
                              "(Barisal, Chittagong, Dhaka, Mymensingh, Noakhali, "
                              "Rajshahi, Sylhet) before sampling."),
        ("Why this set", "Domains proxy for different recording/microphone conditions and "
                          "speech styles: audiobook studio narration, TV broadcast news/"
                          "interviews/talk shows, live parliament floor audio, classroom "
                          "lecture recording, spontaneous kid speech, code-switched medical "
                          "lecture, commentary-style sports speech, and regional dialects."),
        ("What's in 'Test Set' tab", "sample_id, domain, filename, file_path (relative path "
                                      "inside the local banspeech/ folder), "
                                      "ground_truth_transcription_bn, char_count, plus empty "
                                      "columns to paste each ASR model's output transcript and "
                                      "computed WER/CER."),
        ("Random seed", str(args.seed) if args.seed is not None else "none (freshly randomized each run)"),
    ]
    readme_df = pd.DataFrame(readme_rows, columns=[f"Bengali ASR Benchmark — {total}-Sample Test Set", ""])

    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        readme_df.to_excel(writer, sheet_name="README", index=False)
        test_set.to_excel(writer, sheet_name="Test Set", index=False)
        domain_df.to_excel(writer, sheet_name="Domain Summary", index=False)

    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    test_set[["file_path", "domain", "ground_truth_transcription_bn"]].to_csv(
        csv_path, index=False, encoding="utf-8")

    print(f"\n{len(test_set)} samples across {len(domains)} domains")
    print(f"Wavs:  {wavs_dir}/")
    print(f"Excel: {xlsx_path}")
    print(f"CSV:   {csv_path}  (point config.yaml's test_set at this)")


if __name__ == "__main__":
    main()
