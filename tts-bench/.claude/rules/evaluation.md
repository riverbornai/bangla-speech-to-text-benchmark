---
paths:
  - "eval/**"
---
# Evaluation job rules

1. Merge every provider's `manifest.jsonl` for the run → `eval/<run_id>/manifest_all.parquet`.
2. Normalize audio: convert to 24 kHz mono 16-bit WAV, loudness-normalize to −23 LUFS
   (`pyloudnorm`), write to `eval/<run_id>/normalized/`. Never overwrite raw audio.
3. ASR round-trip: transcribe normalized audio with ONE fixed ASR model for all providers
   (record model + version). Compute CER and WER against `spoken_form` and every
   `accepted_variants` entry; keep the minimum.
   Text normalization before scoring (apply to both reference and hypothesis):
   remove punctuation, collapse whitespace, map decomposed য়/ড়/ঢ় to precomposed,
   transliterate any Latin-script tokens to Bangla script (or drop rows with `has_latin=Y`
   from CER and report them separately).
4. Automatic quality: UTMOS (or NISQA) score per clip; record model checkpoint.
5. Failure detection: flag clips with duration < 0.3× or > 3× the expected duration
   (chars × median seconds/char for that provider), leading/trailing silence > 1 s,
   or clipping (> 0.1% samples at full scale).
6. Variance: not measured (each item is synthesized once).
7. Report: per provider × category table (CER, UTMOS, failure rate, p50/p95 latency,
   cost per 1M chars) → `eval/<run_id>/report.xlsx` and `report.md`.
8. Blind pack for human MOS: random `model_code` per provider, shuffled clip order,
   `blind_map.json` stored separately. Rating sheet columns follow the
   `Rating_Template` sheet of the dataset workbook.
