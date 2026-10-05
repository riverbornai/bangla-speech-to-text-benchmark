# Architecture & data flow (always loaded)

```
gs://test-ml-nasim/tts-bench/                   (read-only mount → /mnt/dataset/tts-bench)
  dataset/bangla_tts_benchmark_dataset_v0.1.xlsx
  reference_audio/                              (IndicF5 voice prompts + transcripts)

Cloud Run Job: tts-runner-<env> --provider X [--batch] [--stream]  ──►  provider API (or local GPU model)
        │
        ▼
gs://test-ml-nasim/tts-bench/                   (same bucket, read-write mount → /mnt/audio/tts-bench)
  runs/<run_id>/<provider>/<model>/<voice>/<mode>/<item_id>.<ext>
  runs/<run_id>/<provider>/<model>/<voice>/<mode>/manifest.jsonl
  runs/<run_id>/<provider>/<model>/<voice>/<mode>/run_config.json
  eval/<run_id>/...                             (written by eval job)
```

- Synthesis and evaluation are separate jobs. Synthesis never scores; eval never calls TTS.
- Raw provider audio is stored untouched in its native format. Format conversion and
  loudness normalisation happen only in `eval/` and are written to `eval/<run_id>/normalized/`.
- Blinding for human rating: `eval/` generates a random `model_code` map
  (`eval/<run_id>/blind_map.json`). This file must not be shared with raters.
