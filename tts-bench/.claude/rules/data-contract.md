---
paths:
  - "runner/**/*.py"
  - "eval/**/*.py"
---
# Dataset & output contract

## Input: `bangla_tts_benchmark_dataset_v*.xlsx`, sheet `Dataset`
| column | type | use |
|---|---|---|
| id | str, unique, `BN-<CAT>-NNN` | item_id, file name stem |
| text | str | **exact** string sent to TTS. Never strip, normalize, or NFC it — edge-case rows contain deliberate ZWJ/ZWNJ/decomposed nukta |
| spoken_form | str | reference for CER (eval only) |
| accepted_variants | str, `|`-separated, may be empty | alternate references (eval only) |
| category, subcategory, domain | str | reporting breakdowns |
| difficulty | int 1–3 | reporting |
| length_bucket, char_count, has_digits, has_latin | derived | reporting |
| pronunciation / notes | str | human reviewers |

Validation at startup (fail fast with a clear message): required columns present, ids unique,
no empty `text`. Log row count and the dataset file's GCS generation / mtime.

## Order
Rows are sorted by `id` and processed sequentially in a single task. `--limit N` takes the first N.

## Output: one manifest line per item
```json
{"run_id": "...", "provider": "azure", "model": "...", "voice": "bn-BD-NabanitaNeural",
 "item_id": "BN-NUM-010", "status": "ok|error|skipped_existing|unsupported",
 "audio_path": "runs/.../BN-NUM-010.wav", "format": "wav", "sample_rate": 24000,
 "bytes": 123456, "audio_seconds": 3.42,
 "mode": "stream", "ttfb_ms": 180, "total_ms": 950, "rtf": 0.2778,
 "input_chars": 37, "billed_chars": 37,
 "est_cost_usd": 0.00059, "http_status": 200, "provider_request_id": "...",
 "error": null, "started_at": "ISO8601", "sdk_version": "..."}
```
- `mode`, `ttfb_ms`, `total_ms`, `audio_seconds` and `rtf` are required on every `ok` row;
  see "Latency metrics" in `providers/_contract.md`. In batch mode, `ttfb_ms` is about `total_ms`.
- `est_cost_usd` = billed_chars × price from `config/providers.yaml`; note the price date there.
- An item the provider rejects for language/script reasons is `status: "unsupported"`, not error.
