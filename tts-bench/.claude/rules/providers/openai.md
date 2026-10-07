---
paths:
  - "runner/providers/openai_tts/**"
  - "tests/providers/test_openai_tts.py"
---
# OpenAI TTS

Facts read 2026-10-07 from developers.openai.com (text-to-speech guide + `audio/speech/create` reference).

- Auth: `OPENAI_API_KEY` in `.env`. SDK: `openai` (pinned in `runner/requirements.txt`), `OpenAI(max_retries=0)`;
  `with_retries` owns backoff. The SDK talks through **`httpx2`**, so tests inject an `httpx2.MockTransport`
  into `provider._client` (`respx` cannot mock it).
- Calls: batch = `audio.speech.with_raw_response.create()` (`.parse().content` is the audio, `.headers["x-request-id"]`
  the request id); stream = `audio.speech.with_streaming_response.create()` + `iter_bytes()` through `collect_chunks`.
- Params: `model`, `voice`, `input` (text unchanged), `response_format`. No language parameter (the model infers it),
  no `instructions`, no `speed` in the baseline. `instructions` works on `gpt-4o-mini-tts` only: a variant may add
  "Speak in standard Bangladeshi Bangla"; label it as one.
- **Bengali is not in the docs' TTS language list** (Hindi, Marathi, Tamil, Urdu... are), so config has
  `bangla_support: unofficial`. Treat results as a capability test; expect high CER on digits and code-mix.
- Output: batch asks for `wav`, stream for raw `pcm` (docs: 24 kHz, 16-bit signed little-endian), wrapped with
  `base.pcm_to_wav` because a streamed WAV header may carry a placeholder length. The stored clip is always WAV.
  Still to confirm with one live call: the WAV header's sample rate, and that the PCM is mono.
- Limits: 4096 chars (reference page) vs a 2000-token input limit (model page). Bangla is token-heavy, so the
  token limit may bite first: confirm on the longest dataset item before trusting `max_chars`.
- Errors: `APIStatusError` -> `ProviderError(status, error.code|type, request id, Retry-After)`; `e.body` is the inner
  error object (`{message, type, code}`), only the short code is kept. `APIConnectionError` (incl. timeouts)
  -> `ProviderError(None, <class name>)`.
- Billing is **tokens**, not characters (`gpt-4o-mini-tts`: $0.60 / 1M text-input tokens, $12.00 / 1M audio-output
  tokens on the model page); `billed_chars` is input chars only and `est_cost_usd` stays null until a price is set.
  Rate limits (Build tier): 2,000 RPM, 150,000 TPM; one request at a time stays far below them.
- Models: `gpt-4o-mini-tts` (snapshot `gpt-4o-mini-tts-2025-12-15`), `tts-1`, `tts-1-hd`. Voices (13): alloy, ash,
  ballad, coral, echo, fable, nova, onyx, sage, shimmer, verse, marin, cedar (`tts-1*` lack ballad/verse/marin/cedar).
  Benchmark one F and one M voice as separate configs.
