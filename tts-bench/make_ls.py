# make_ls_tasks.py
import json, sys

BUCKET = "test-ml-nasim"
PREFIX = "tts-bench/"                    # folder the audio mount points at
MANIFEST = sys.argv[1]                   # e.g. manifest_all.jsonl
OUT = sys.argv[2] if len(sys.argv) > 2 else "ls_tasks.json"

def as_list(v):
    """accepted_variants may arrive as list, '|'-separated string, or null."""
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return [s.strip() for s in str(v).split("|") if s.strip()]

tasks = []
with open(MANIFEST, encoding="utf-8") as f:
    for line in f:
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("status") != "ok":
            continue

        variants = as_list(r.get("accepted_variants"))
        tasks.append({
            "data": {
                "audio": f"gs://{BUCKET}/{PREFIX}{r['audio_path']}",
                "run_id": r["run_id"],
                "item_id": r["item_id"],
                "text": r.get("text", ""),
                "spoken_form": r.get("spoken_form", ""),
                "accepted_variants": variants,                                # list of strings
                "accepted_variants_display": " | ".join(variants) or "—",     # for <Text> display
                "meta": {
                    "run_id": r["run_id"],
                    "item_id": r["item_id"],
                    "mode": r.get("mode"),
                    "format": r.get("format"),
                    "duration (s)": r.get("audio_seconds"),
                    "sample rate": r.get("sample_rate"),
                },
                "provider": r["provider"],
                "model": r["model"],
                "voice": r["voice"],
            }
        })

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(tasks, f, ensure_ascii=False, indent=2)
print(f"{len(tasks)} tasks -> {OUT}")