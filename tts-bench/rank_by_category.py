#!/usr/bin/env python3
"""Rank TTS models by average human rating, per category.

Reads a Label Studio export (output.json). In each task, `rating{i}` rates
`audio{i}`, which was produced by `model{i}` (the order is shuffled per task,
so ratings are mapped back to models via the task's own model{i} field).

Usage:
    python rank_by_category.py                  # every category, plus overall
    python rank_by_category.py --category ABR   # one category
    python rank_by_category.py -c CUR --json    # print JSON to stdout
    python rank_by_category.py -o rankings.json # write JSON to a file
    python rank_by_category.py -i other.json
"""
import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path


def collect(tasks):
    """Return {category: {model: [ratings]}}; skips cancelled annotations."""
    scores = defaultdict(lambda: defaultdict(list))
    task_counts = defaultdict(int)
    for task in tasks:
        data = task.get("data", {})
        category = data.get("category", "UNKNOWN")
        if any(not a.get("was_cancelled") for a in task.get("annotations", [])):
            task_counts[category] += 1
        for ann in task.get("annotations", []):
            if ann.get("was_cancelled"):
                continue
            for res in ann.get("result", []):
                if res.get("type") != "rating":
                    continue
                m = re.fullmatch(r"rating(\d+)", res.get("from_name", ""))
                if not m:
                    continue
                model = data.get(f"model{m.group(1)}")
                rating = res.get("value", {}).get("rating")
                if model is None or rating is None:
                    continue
                scores[category][model].append(rating)
    return scores, task_counts


def rank(model_ratings):
    """Rows sorted by avg rating high -> low (ties: more ratings, then name)."""
    rows = [
        {
            "model": model,
            "avg_rating": round(sum(r) / len(r), 2),
            "n": len(r),
            "distribution": {str(s): r.count(s) for s in range(5, 0, -1)},
        }
        for model, r in model_ratings.items()
    ]
    rows.sort(key=lambda x: (-x["avg_rating"], -x["n"], x["model"]))
    for i, row in enumerate(rows, 1):
        row["rank"] = i
    return rows


def print_table(title, rows):
    print(f"\n=== {title} ===")
    print(f"{'#':<3} {'Model':<18} {'Avg':>5} {'N':>3}   5★ 4★ 3★ 2★ 1★")
    for r in rows:
        d = r["distribution"]
        print(f"{r['rank']:<3} {r['model']:<18} {r['avg_rating']:>5.2f} {r['n']:>3}   "
              + " ".join(f"{d[str(s)]:>2} " for s in range(5, 0, -1)))


def main():
    here = Path(__file__).parent
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-i", "--input", default=here / "output.json")
    p.add_argument("-c", "--category", help="e.g. ABR, CUR, DOM (case-insensitive). Omit for all.")
    p.add_argument("--json", action="store_true", help="print JSON to stdout instead of tables")
    p.add_argument("-o", "--output", help="write JSON to this file (e.g. rankings.json)")
    args = p.parse_args()

    tasks = json.loads(Path(args.input).read_text(encoding="utf-8"))
    scores, task_counts = collect(tasks)

    if args.category:
        cat = args.category.upper()
        if cat not in scores:
            sys.exit(f"Unknown category '{args.category}'. Available: {', '.join(sorted(scores))}")
        selected = {cat: scores[cat]}
    else:
        selected = dict(sorted(scores.items()))

    result = {
        "source": Path(args.input).name,
        "categories": {
            cat: {"tasks": task_counts[cat], "ranking": rank(models)}
            for cat, models in selected.items()
        },
    }
    if not args.category:
        overall = defaultdict(list)
        for models in selected.values():
            for model, r in models.items():
                overall[model].extend(r)
        result["overall"] = {
            "tasks": sum(task_counts[c] for c in selected),
            "ranking": rank(overall),
        }

    if args.output:
        Path(args.output).write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {args.output}", file=sys.stderr)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif not args.output:
        for cat, block in result["categories"].items():
            print_table(cat, block["ranking"])
        if "overall" in result:
            print_table("OVERALL", result["overall"]["ranking"])


if __name__ == "__main__":
    main()
