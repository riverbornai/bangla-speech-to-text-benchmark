#!/usr/bin/env python3
"""Build Label Studio tasks.json for a blind 7-way TTS comparison.

Reads every *_batch_manifest.jsonl in this folder (one per TTS model),
shuffles the model order independently for each sentence, and writes
tasks.json plus labeling_config.xml.

Usage:
    python3 make_tasks.py --bucket https://your-host/audio
Audio URL = <bucket>/<audio_path from manifest>, e.g.
    https://your-host/audio/runs/azure-prod/azure/neural/bn-BD-NabanitaNeural/batch/BN-ABR-001.wav
"""
import argparse, glob, json, os, random
from urllib.parse import quote

ap = argparse.ArgumentParser()
ap.add_argument("--bucket", default="https://your-host/audio", help="base URL the runs/ folder is served under")
ap.add_argument("--manifests", default=os.path.dirname(os.path.abspath(__file__)))
ap.add_argument("--out", default=os.path.dirname(os.path.abspath(__file__)))
ap.add_argument("--seed", type=int, default=42)
ap.add_argument("--text-model", default="azure-prod",
                help="run_id whose 'text' is shown to annotators (use one whose input has no style tags)")
args = ap.parse_args()
bucket = args.bucket.rstrip("/")

# model name = run_id; one manifest per model
runs = {}
for path in sorted(glob.glob(os.path.join(args.manifests, "*_batch_manifest.jsonl"))):
    with open(path, encoding="utf-8") as f:
        rows = [json.loads(l) for l in f if l.strip()]
    runs[rows[0]["run_id"]] = {r["item_id"]: r for r in rows}

models = sorted(runs)
assert len(models) >= 2, "no manifests found"
item_ids = list(runs[args.text_model])
for m in models:  # every model must cover every sentence
    missing = set(item_ids) - set(runs[m])
    assert not missing, f"{m} missing {sorted(missing)[:3]}"

random.seed(args.seed)  # reproducible shuffle
tasks = []
for iid in item_ids:
    ref = runs[args.text_model][iid]
    order = models[:]
    random.shuffle(order)  # new random order for each sentence
    data = {
        "item_id": iid,
        "category": iid.split("-")[1],
        "text": ref["text"],
        "spoken_form": ref["spoken_form"],
        "accepted_variants": ref["accepted_variants"],
    }
    for slot, m in enumerate(order, start=1):
        path = quote(runs[m][iid]["audio_path"], safe="/:")  # keep ':' literal (e.g. bulbul:v3)
        data[f"audio{slot}"] = f"{bucket}/{path}"
        data[f"model{slot}"] = m  # answer key; not shown unless the config references it
    tasks.append({"data": data})

with open(os.path.join(args.out, "tasks.json"), "w", encoding="utf-8") as f:
    json.dump(tasks, f, indent=2, ensure_ascii=False)

n = len(models)
audio = "\n".join(
    f'  <Header value="Audio {i}"/>\n  <Audio name="audio{i}" value="$audio{i}"/>' for i in range(1, n + 1))
ratings = "\n".join(
    f'  <Rating name="rating{i}" toName="audio{i}" maxRating="5" required="true"/>' for i in range(1, n + 1))
cfg = f'''<View>
  <Header value="Sentence"/>
  <Text name="text" value="$text"/>
{audio}
  <Header value="Rate each audio (naturalness / pronunciation)"/>
{ratings}
</View>
'''
with open(os.path.join(args.out, "labeling_config.xml"), "w", encoding="utf-8") as f:
    f.write(cfg)

print(f"Wrote {len(tasks)} tasks, {n} models: {', '.join(models)}")
