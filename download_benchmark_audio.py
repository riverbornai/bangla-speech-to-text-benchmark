"""
Downloads the BanSpeech wav files listed in the benchmark test set from
Hugging Face into <audio_dir>/<domain>/<filename>.wav.

By default it reads data/test_set.csv and writes to config.yaml's audio_dir
(wavs_1001/), which is exactly what the batch and streaming runners expect.
Only the parquet shards for the needed domains are downloaded.

Requirements:  pip install -r requirements.txt
Run:           python download_benchmark_audio.py
               python download_benchmark_audio.py --test-set data/test_set.csv --out wavs_1001
"""
import argparse
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import yaml
from huggingface_hub import list_repo_files, hf_hub_download

ROOT = os.path.dirname(os.path.abspath(__file__))
REPO_ID = "SUST-CSE-Speech/banspeech"


def main():
    cfg = yaml.safe_load(open(os.path.join(ROOT, "config.yaml")))
    ap = argparse.ArgumentParser()
    ap.add_argument("--test-set", default=cfg["test_set"],
                    help="csv with a file_path column (default: config.yaml's test_set)")
    ap.add_argument("--out", default=cfg["audio_dir"],
                    help="output folder (default: config.yaml's audio_dir)")
    args = ap.parse_args()

    out_dir = os.path.join(ROOT, args.out)
    test_set = pd.read_csv(os.path.join(ROOT, args.test_set), dtype=str)
    targets = set(test_set["file_path"].str.strip())

    # Group targets by domain so each parquet shard is read once.
    targets_by_domain = {}
    for p in targets:
        parts = p.strip("/").split("/")
        if len(parts) >= 2:
            targets_by_domain.setdefault(parts[0], set()).add(p)

    print(f"Need {len(targets)} files across {len(targets_by_domain)} domains")

    print("Fetching dataset file list from Hugging Face...")
    repo_files = list_repo_files(REPO_ID, repo_type="dataset")
    domain_to_parquet = {}
    for f in repo_files:
        if f.startswith("data/") and f.endswith(".parquet"):
            basename = os.path.basename(f)
            if "-00000-" in basename:
                domain_to_parquet[basename.split("-00000-")[0]] = f

    def process_domain(domain, domain_targets):
        parquet_file = domain_to_parquet.get(domain)
        if not parquet_file:
            print(f"[{domain}] Error: no parquet file found")
            return domain, 0

        local_path = hf_hub_download(repo_id=REPO_ID, filename=parquet_file, repo_type="dataset")
        df = pd.read_parquet(local_path, columns=["audio", "file_path"])

        found = 0
        for _, row in df.iterrows():
            file_path = row["file_path"]
            if file_path in domain_targets:
                out_path = os.path.join(out_dir, file_path.lstrip("/"))
                os.makedirs(os.path.dirname(out_path), exist_ok=True)
                with open(out_path, "wb") as out_f:
                    out_f.write(row["audio"]["bytes"])
                found += 1
                if found == len(domain_targets):
                    break

        print(f"  -> saved {found}/{len(domain_targets)} files from {domain}")
        return domain, found

    start_time = time.time()
    total_saved = 0
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(process_domain, d, t): d for d, t in targets_by_domain.items()}
        for future in as_completed(futures):
            domain = futures[future]
            try:
                total_saved += future.result()[1]
            except Exception as e:
                print(f"[{domain}] Failed with error: {e}")

    print(f"Done. Saved {total_saved}/{len(targets)} files under {out_dir}/ "
          f"in {time.time() - start_time:.2f} seconds.")


if __name__ == "__main__":
    main()
