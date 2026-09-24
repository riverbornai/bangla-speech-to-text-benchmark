"""Load ground-truth references from the benchmark test set (.csv or .xlsx)."""
import pandas as pd


def load_references(path: str) -> dict:
    """
    Return {file_path: {"domain": str, "ref": str}} keyed by the BanSpeech
    file_path (e.g. "/audio_books/book_10_d_164.wav"), which is also how the
    downloaded wavs are addressed on disk.

    Accepts the checked-in data/test_set.csv, or an xlsx written by
    src/build_benchmark_set.py (its "Test Set" sheet).
    """
    if path.endswith(".csv"):
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
    else:
        df = pd.read_excel(path, sheet_name="Test Set")
    refs = {}
    for _, row in df.iterrows():
        fp = str(row["file_path"]).strip()
        if not fp or fp == "nan":
            continue
        refs[fp] = {
            "domain": str(row["domain"]).strip(),
            "ref": str(row["ground_truth_transcription_bn"]),
        }
    return refs


if __name__ == "__main__":
    import sys
    r = load_references(sys.argv[1] if len(sys.argv) > 1 else "data/test_set.csv")
    print(f"{len(r)} references loaded")
    k = next(iter(r))
    print(k, "->", r[k]["domain"], "|", r[k]["ref"][:60])
