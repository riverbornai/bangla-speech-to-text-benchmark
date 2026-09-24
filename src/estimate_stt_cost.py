#!/usr/bin/env python3
"""
estimate_stt_cost.py
--------------------
Estimate speech-to-text (STT) API cost for a folder of WAV files across one or
more providers, using the rates and billing-resolution rules from the
Sept-2026 pricing comparison. Output is an Excel (.xlsx) workbook.

What it does
  1. Prepares a pricing.json file (writes an embedded default if missing).
  2. Recursively scans a source folder (nested folders supported) for audio.
  3. For each file + each requested provider, computes the *billed* duration
     (ceiling seconds, per that provider's rounding / minimum / per-channel
     rules) and the estimated USD cost.
  4. Writes an .xlsx with three sheets: Estimates (per file x model),
     Summary by Model, and Assumptions & Rates. (Pass an .csv path to --out
     to get CSV instead.)

Standard library + openpyxl (preinstalled in most data environments).

Examples
  python estimate_stt_cost.py --source ./audio --providers all --out costs.xlsx
  python estimate_stt_cost.py -s ./calls -p groq_whisper openai_4o gemini_25_flash
  python estimate_stt_cost.py --write-pricing        # (re)create pricing.json

Accuracy notes
  * Input-audio cost is deterministic from audio duration. OUTPUT-text cost
    (Gemini, Soniox) is ESTIMATED from words-per-minute assumptions in
    pricing.json and shown separately in the Assumptions sheet.
  * Google and Groq bill each audio channel separately -> "bill_per_channel".
"""

import argparse
import csv
import json
import math
import os
import sys
import wave

# --------------------------------------------------------------------------- #
# Embedded default pricing (mirrors the corrected comparison table).
# --------------------------------------------------------------------------- #
DEFAULT_PRICING = {
    "meta": {
        "source": "STT pricing comparison (September 2026)",
        "note": "Rates verified against official provider pages. Output-text "
                "cost for token-billed models is an estimate.",
    },
    "usd_per_inr": round(1 / 83.0, 8),           # ~Rs.83/USD (Sarvam only)
    "assumptions": {
        "output_words_per_minute": 150,
        "tokens_per_word": 1.3,
    },
    "providers": {
        "groq_whisper": {
            "provider": "Groq", "model": "whisper-large-v3",
            "billing": "duration", "usd_per_hour": 0.111,
            "rounding": "ceil_second", "min_billed_seconds": 10,
            "bill_per_channel": True,
            "resolution_note": "per second, 10-second minimum per request",
        },
        "openai_4o": {
            "provider": "OpenAI", "model": "gpt-4o-transcribe",
            "billing": "duration", "usd_per_hour": 0.36,
            "rounding": "nearest_second", "min_billed_seconds": 0,
            "bill_per_channel": False,
            "resolution_note": "rounded to nearest second",
        },
        "sarvam_stt": {
            "provider": "Sarvam AI", "model": "Speech-to-Text (Saaras v4)",
            "billing": "duration", "inr_per_hour": 30.0,
            "rounding": "ceil_second", "min_billed_seconds": 0,
            "bill_per_channel": False,
            "resolution_note": "per second, rounded up to nearest second",
        },
        "elevenlabs_scribe": {
            "provider": "ElevenLabs", "model": "scribe_v2",
            "billing": "duration", "usd_per_hour": 0.22,
            "rounding": "ceil_second", "min_billed_seconds": 0,
            "bill_per_channel": False,
            "resolution_note": "per second of audio processed",
        },
        "deepgram_nova3": {
            "provider": "Deepgram", "model": "nova-3",
            "billing": "duration", "usd_per_hour": 0.258,
            "rounding": "ceil_second", "min_billed_seconds": 0,
            "bill_per_channel": False,
            "resolution_note": "per second, no minute rounding",
        },
        "soniox": {
            "provider": "Soniox", "model": "stt-async",
            "billing": "token",
            "input_audio_tokens_per_second": 30000 / 3600.0,
            "usd_per_1m_input_audio": 1.50,
            "output_text_tokens_per_minute": 250,
            "usd_per_1m_output_text": 3.50,
            "bill_per_channel": False,
            "resolution_note": "per token (~30k input tokens/hr)",
        },
        "google_chirp2": {
            "provider": "Google Cloud STT v2", "model": "chirp_2",
            "billing": "duration", "usd_per_hour": 0.96,
            "rounding": "ceil_second", "min_billed_seconds": 0,
            "bill_per_channel": True,
            "resolution_note": "rounded up to nearest 1 second per request; "
                               "each channel billed separately",
        },
        "gemini_25_flash": {
            "provider": "Gemini", "model": "gemini-2.5-flash",
            "billing": "token",
            "input_audio_tokens_per_second": 32,
            "usd_per_1m_input_audio": 1.00,
            "output_from_words": True,
            "usd_per_1m_output_text": 2.50,
            "bill_per_channel": False,
            "resolution_note": "per token (audio = 32 tokens/second); estimate",
        },
    },
}

AUDIO_EXTS_DEFAULT = [".wav"]


# --------------------------------------------------------------------------- #
# Pricing file handling
# --------------------------------------------------------------------------- #
def ensure_pricing(path, force=False):
    if force or not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(DEFAULT_PRICING, fh, indent=2)
        print(f"[pricing] wrote {path}")
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


# --------------------------------------------------------------------------- #
# Audio duration
# --------------------------------------------------------------------------- #
def wav_info(path):
    with wave.open(path, "rb") as w:
        frames, rate, channels = w.getnframes(), w.getframerate(), w.getnchannels()
        if rate == 0:
            raise ValueError("frame rate is 0")
        return frames / float(rate), channels


def audio_info(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".wav":
        return wav_info(path)
    try:
        import soundfile as sf  # optional, for non-wav
        info = sf.info(path)
        return info.frames / float(info.samplerate), info.channels
    except Exception as exc:
        raise RuntimeError(f"cannot read '{ext}' without soundfile ({exc})")


# --------------------------------------------------------------------------- #
# Cost calculation
# --------------------------------------------------------------------------- #
def _round_seconds(duration_s, mode):
    if mode == "nearest_second":
        return float(round(duration_s))
    if mode == "none":
        return float(duration_s)
    return float(math.ceil(duration_s))          # default: ceiling


def estimate(cfg, duration_s, channels, pricing):
    """Return billed_seconds (ceiling, per model rule), token counts, cost."""
    chan_mult = channels if cfg.get("bill_per_channel") else 1

    if cfg["billing"] == "duration":
        billed = _round_seconds(duration_s, cfg.get("rounding", "ceil_second"))
        billed = max(billed, float(cfg.get("min_billed_seconds", 0)))
        billed *= chan_mult
        usd_per_hour = cfg.get("usd_per_hour")
        if usd_per_hour is None and "inr_per_hour" in cfg:
            usd_per_hour = cfg["inr_per_hour"] * pricing["usd_per_inr"]
        cost = (billed / 3600.0) * usd_per_hour
        return {"billed_seconds": billed, "input_tokens": "",
                "output_tokens": "", "est_cost_usd": cost}

    if cfg["billing"] == "token":
        a = pricing["assumptions"]
        billed = math.ceil(duration_s) * chan_mult          # ceiling ref seconds
        in_tok = duration_s * cfg["input_audio_tokens_per_second"] * chan_mult
        if cfg.get("output_text_tokens_per_minute") is not None:
            out_tok = (duration_s / 60.0) * cfg["output_text_tokens_per_minute"]
        elif cfg.get("output_from_words"):
            out_tok = (duration_s / 60.0) * a["output_words_per_minute"] * a["tokens_per_word"]
        else:
            out_tok = 0.0
        cost = (in_tok / 1e6) * cfg["usd_per_1m_input_audio"]
        cost += (out_tok / 1e6) * cfg.get("usd_per_1m_output_text", 0.0)
        return {"billed_seconds": billed, "input_tokens": round(in_tok, 1),
                "output_tokens": round(out_tok, 1), "est_cost_usd": cost}

    raise ValueError(f"unknown billing type: {cfg['billing']}")


# --------------------------------------------------------------------------- #
# File discovery
# --------------------------------------------------------------------------- #
def find_audio(source, exts):
    exts = tuple(e.lower() for e in exts)
    for root, _dirs, files in os.walk(source):
        for name in sorted(files):
            if name.lower().endswith(exts):
                yield os.path.join(root, name)


# --------------------------------------------------------------------------- #
# Output writers
# --------------------------------------------------------------------------- #
MAIN_COLUMNS = [
    ("file", "File"),
    ("provider", "Provider"),
    ("model_name", "Model Name"),
    ("model_id", "Model ID"),
    ("duration_seconds", "Duration (s)"),
    ("channels", "Channels"),
    ("billed_seconds", "Billed Seconds (ceiling)"),
    ("est_cost_usd", "Estimated Cost (USD)"),
]


def write_csv(path, records):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow([h for _k, h in MAIN_COLUMNS])
        for r in records:
            w.writerow([round(r[k], 6) if k == "est_cost_usd" else r[k]
                        for k, _h in MAIN_COLUMNS])
    print(f"[out] wrote {path}")


def _autosize(ws, glc):
    for col in ws.columns:
        vals = [len(str(c.value)) for c in col if c.value is not None]
        width = min(max((max(vals) if vals else 8) + 2, 10), 60)
        ws.column_dimensions[glc(col[0].column)].width = width


def write_xlsx(path, records, totals, provider_ids, pricing, n_files):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter as glc

    hfont = Font(name="Arial", bold=True, color="FFFFFF")
    hfill = PatternFill("solid", fgColor="305496")
    bfont = Font(name="Arial")

    def header(ws, headers):
        ws.append(headers)
        for c in range(1, len(headers) + 1):
            cell = ws.cell(row=1, column=c)
            cell.font = hfont
            cell.fill = hfill
            cell.alignment = Alignment(horizontal="center", vertical="center")

    wb = Workbook()

    # ---- Sheet 1: Estimates (per file x model) ---------------------------- #
    ws = wb.active
    ws.title = "Estimates"
    keys = [k for k, _h in MAIN_COLUMNS]
    header(ws, [h for _k, h in MAIN_COLUMNS])
    for r in records:
        ws.append([r[k] for k in keys])
    cost_i = keys.index("est_cost_usd")
    dur_i = keys.index("duration_seconds")
    bill_i = keys.index("billed_seconds")
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
        for cell in row:
            cell.font = bfont
        row[cost_i].number_format = "$0.000000"
        row[dur_i].number_format = "#,##0.00"
        row[bill_i].number_format = "#,##0"
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{glc(len(keys))}{ws.max_row}"
    _autosize(ws, glc)

    # ---- Sheet 2: Summary by Model ---------------------------------------- #
    ws2 = wb.create_sheet("Summary by Model")
    header(ws2, ["Provider", "Model Name", "Model ID", "Files",
                 "Total Audio (s)", "Total Billed Seconds",
                 "Total Est. Cost (USD)"])
    counts = {}
    for r in records:
        counts[r["model_id"]] = counts.get(r["model_id"], 0) + 1
    for pid in sorted(provider_ids, key=lambda p: totals[p]["cost"]):
        cfg = pricing["providers"][pid]
        ws2.append([cfg["provider"], cfg["model"], pid, counts.get(pid, 0),
                    round(totals[pid]["seconds"], 2),
                    round(totals[pid]["billed"], 0),
                    totals[pid]["cost"]])
    for row in ws2.iter_rows(min_row=2, max_row=ws2.max_row):
        for cell in row:
            cell.font = bfont
        row[4].number_format = "#,##0.00"
        row[5].number_format = "#,##0"
        row[6].number_format = "$0.0000"
    ws2.freeze_panes = "A2"
    _autosize(ws2, glc)

    # ---- Sheet 3: Assumptions & Rates ------------------------------------- #
    ws3 = wb.create_sheet("Assumptions & Rates")
    header(ws3, ["Parameter", "Value"])
    a = pricing["assumptions"]
    for label, val in [
        ("USD per INR", pricing["usd_per_inr"]),
        ("Output words/minute (estimate)", a["output_words_per_minute"]),
        ("Tokens per word (estimate)", a["tokens_per_word"]),
        ("Audio files scanned", n_files),
    ]:
        ws3.append([label, val])
    ws3.append([])
    trow = ws3.max_row + 1
    header_cells = ["Model ID", "Provider", "Model Name", "Rate", "Billing resolution"]
    ws3.append(header_cells)
    for c in range(1, len(header_cells) + 1):
        cell = ws3.cell(row=trow, column=c)
        cell.font = hfont
        cell.fill = hfill
    for pid in provider_ids:
        cfg = pricing["providers"][pid]
        if cfg["billing"] == "duration":
            if cfg.get("usd_per_hour") is not None:
                rate = f'${cfg["usd_per_hour"]}/hr'
            else:
                usd = round(cfg["inr_per_hour"] * pricing["usd_per_inr"], 4)
                rate = f'INR {cfg["inr_per_hour"]}/hr (~${usd}/hr)'
        else:
            rate = (f'${cfg["usd_per_1m_input_audio"]}/1M audio-tok in, '
                    f'${cfg.get("usd_per_1m_output_text", 0)}/1M text-tok out')
        ws3.append([pid, cfg["provider"], cfg["model"], rate,
                    cfg.get("resolution_note", "")])
    ws3.append([])
    ws3.append(["Note:", "Billed Seconds = audio duration billed by each model "
                "(ceiling; Groq applies a 10s minimum, OpenAI rounds to nearest "
                "second, Google & Groq bill each channel separately). Token "
                "models (Soniox, Gemini) bill per token; output-text cost is "
                "estimated from the words/minute assumption above."])
    for r in ws3.iter_rows(min_row=2, max_row=ws3.max_row):
        for cell in r:
            if cell.font is None or not cell.font.bold:
                cell.font = bfont
    _autosize(ws3, glc)

    wb.save(path)
    print(f"[out] wrote {path}")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Estimate STT cost for a folder of audio files (-> .xlsx).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("-s", "--source", help="Source folder (scanned recursively)")
    ap.add_argument("-p", "--providers", nargs="+", default=["all"],
                    help="Provider IDs, or 'all'. See pricing.json for the list.")
    ap.add_argument("-o", "--out", default="stt_costs.xlsx",
                    help="Output path. .xlsx (default) or .csv")
    ap.add_argument("--pricing",
                    default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         "pricing.json"),
                    help="Path to pricing.json (created if missing)")
    ap.add_argument("--ext", nargs="+", default=AUDIO_EXTS_DEFAULT,
                    help="Audio extensions to include")
    ap.add_argument("--write-pricing", action="store_true",
                    help="(Re)write pricing.json from embedded defaults and exit")
    args = ap.parse_args(argv)

    pricing = ensure_pricing(args.pricing, force=args.write_pricing)
    if args.write_pricing:
        return 0

    if not args.source:
        ap.error("--source is required (unless using --write-pricing)")
    if not os.path.isdir(args.source):
        ap.error(f"source folder not found: {args.source}")

    all_ids = list(pricing["providers"].keys())
    if len(args.providers) == 1 and args.providers[0].lower() == "all":
        provider_ids = all_ids
    else:
        provider_ids = args.providers
        unknown = [p for p in provider_ids if p not in pricing["providers"]]
        if unknown:
            ap.error(f"unknown provider(s): {', '.join(unknown)}\n"
                     f"available: {', '.join(all_ids)}")

    records = []
    totals = {pid: {"cost": 0.0, "seconds": 0.0, "billed": 0.0}
              for pid in provider_ids}
    n_files = 0

    for path in find_audio(args.source, args.ext):
        try:
            duration_s, channels = audio_info(path)
        except Exception as exc:
            print(f"[skip] {path}: {exc}", file=sys.stderr)
            continue
        n_files += 1
        for pid in provider_ids:
            cfg = pricing["providers"][pid]
            est = estimate(cfg, duration_s, channels, pricing)
            records.append({
                "file": os.path.relpath(path, args.source),
                "provider": cfg["provider"],
                "model_name": cfg["model"],
                "model_id": pid,
                "duration_seconds": round(duration_s, 3),
                "channels": channels,
                "billed_seconds": est["billed_seconds"],
                "est_cost_usd": round(est["est_cost_usd"], 6),
            })
            totals[pid]["cost"] += est["est_cost_usd"]
            totals[pid]["seconds"] += duration_s
            totals[pid]["billed"] += float(est["billed_seconds"])

    ext = os.path.splitext(args.out)[1].lower()
    if ext == ".csv":
        write_csv(args.out, records)
    else:
        write_xlsx(args.out, records, totals, provider_ids, pricing, n_files)

    # ---- console summary --------------------------------------------------- #
    print(f"\nScanned {n_files} audio file(s); {len(records)} row(s).")
    if n_files:
        hrs = totals[provider_ids[0]]["seconds"] / 3600.0
        print(f"Total audio: {hrs:.3f} hours\n")
        w = max(len(pid) for pid in provider_ids)
        print(f"{'provider_id':<{w}}  {'model':<28}  {'est. total (USD)':>16}")
        print("-" * (w + 48))
        for pid in sorted(provider_ids, key=lambda p: totals[p]["cost"]):
            print(f"{pid:<{w}}  {pricing['providers'][pid]['model']:<28}  "
                  f"{totals[pid]['cost']:>16.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
