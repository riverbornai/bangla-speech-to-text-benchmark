---
paths:
  - "runner/providers/cartesia/**"
  - "tests/providers/test_cartesia.py"
---
# Cartesia Sonic

Facts read from the docs and SDK on 2026-10-07; re-check before each round.

- Secret: `CARTESIA_API_KEY` in `.env`. SDK: `cartesia` (pinned in `runner/requirements.txt`), built on `httpx`.
  The SDK sends `Cartesia-Version: 2026-08-14` itself (the only valid value today); don't set it by hand.
- Model: `sonic-3.6` (alias `sonic-latest`; `sonic-3.5`, `sonic-3` still exist). Bengali `bn` is listed for
  3.6. Send `language="bn"` only: `locale` (e.g. `bn-BD`) is undocumented, and never send both.
- Voice: no Bengali-specific voices are documented. Choose one with `Cartesia().voices.list(language="bn")`
  (or a multilingual voice), then record the id and the reason in providers.yaml. Sent as
  `voice={"mode": "id", "id": ...}`.
- Batch: `tts.generate()` -> `POST /tts/bytes`, `output_format={"container": "wav", "encoding": "pcm_s16le",
  "sample_rate": 24000}`; read the bytes with `.read()`.
- Stream: `tts.generate_sse()` -> `POST /tts/sse`. SSE documents only raw encodings, so it asks for
  `container: "raw"` (yaml `stream: {output_format: pcm_24000}`) and the runner wraps the PCM as WAV.
  Chunk events carry base64 audio in `.data`; an in-band `error` event raises `ProviderError` with only its
  `error_code`. TTFB is the first non-empty chunk. SSE with `container: "wav"` is unverified.
- Errors: `APIStatusError` (status, `.body`, `.response.headers`) and `APIConnectionError` (incl. timeouts).
  The body has `error_code`, `title`, `message`, `request_id`; keep only `error_code` + `request_id`.
  The SDK retries by default, so it is created with `max_retries=0` (retries are `with_retries`).
- Success responses expose no documented request id, so `request_id` is null; the chunk `context_id` is not one.
- Limits: no max input length documented, so `max_chars` is unset. TTS concurrency by plan: Free 2, Pro 3,
  Startup 5, Scale 15 (we use 1); over the limit is a 429.
- Billing: 1 credit = 1 character, plan-dependent ($/1M credits), so set `usd_per_unit` for your plan.
- Inline controls (Sonic-3 transcript tags, used by the emotive variant): `<emotion value="..."/>` (beta,
  English-only per docs), `<speed ratio="..."/>`, `<volume ratio="..."/>`, `<break time="300ms"/>`.
  Baseline sends the plain text with default speed and emotion.
- Cartesia's selling point is latency: run a separate latency-only pass from a region close to their API,
  with concurrency 1, so numbers are comparable.
