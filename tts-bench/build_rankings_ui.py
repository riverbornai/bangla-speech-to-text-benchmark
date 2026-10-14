#!/usr/bin/env python3
"""Embed the current rankings.json into rankings_ui.html as an offline snapshot.

The page always tries to fetch ./rankings.json first (when served over http).
The embedded snapshot lets it work when double-clicked from disk (file://).

Usage:
    python build_rankings_ui.py                       # rankings.json -> rankings_ui.html
    python build_rankings_ui.py -i other.json -o out.html
"""
import argparse
import json
import re
from pathlib import Path

here = Path(__file__).parent
p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
p.add_argument("-i", "--input", default=here / "rankings.json")
p.add_argument("-o", "--output", default=here / "rankings_ui.html")
args = p.parse_args()

data = json.loads(Path(args.input).read_text(encoding="utf-8"))
payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")

html = Path(args.output).read_text(encoding="utf-8")
pattern = re.compile(r'(<script id="embedded-data" type="application/json">)(.*?)(</script>)', re.S)
if not pattern.search(html):
    raise SystemExit("embedded-data block not found in " + str(args.output))
html = pattern.sub(lambda m: m.group(1) + payload + m.group(3), html, count=1)
Path(args.output).write_text(html, encoding="utf-8")
print(f"Embedded {args.input} -> {args.output}")
