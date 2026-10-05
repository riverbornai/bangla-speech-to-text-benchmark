---
paths:
  - "runner/**/*.py"
  - "eval/**/*.py"
  - "**/Dockerfile"
---
# Python & container rules

- Python 3.12, type hints everywhere, `ruff` for lint/format, `pytest` for tests.
- Dependencies pinned in `requirements.txt` (exact versions). Provider SDKs imported lazily
  inside each provider module so one broken SDK doesn't break all providers.
- Config via env vars + `config/providers.yaml`; parse once into a frozen dataclass.
- Retries: exponential backoff with jitter on 429/5xx only (max 5 attempts). Never retry 4xx
  other than 429. Record the attempt count in the manifest.
- No concurrency: a plain synchronous loop over the rows (one request at a time).
- Timing: `time.perf_counter_ns()`; TTFB = first audio chunk received, total = last byte, RTF =
  total / audio duration (see "Latency metrics" in `providers/_contract.md`).
- Logging: structured JSON to stdout (Cloud Logging picks it up). Include run_id, provider,
  item_id, status, total_ms. Never log text of secrets or auth headers.
- Exit code: non-zero only if > `MAX_ERROR_RATE` (default 20%) of items failed, so a few
  provider hiccups don't cause Cloud Run to retry the whole task.
- Dockerfile: `python:3.12-slim`, non-root user, `ffmpeg` installed (needed by eval and for
  reading audio duration), no secrets in build args (keys come from the copied `.env`), `ENTRYPOINT ["python","-m","runner.main"]`.
- Unit tests must mock provider HTTP calls — tests never hit paid APIs.
