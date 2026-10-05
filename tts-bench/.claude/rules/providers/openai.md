---
paths:
  - "runner/providers/openai_tts.py"
  - "tests/providers/test_openai_tts.py"
---
# OpenAI TTS

- Secret: `OPENAI_API_KEY`. Endpoint `/v1/audio/speech`; model from providers.yaml
  (e.g. `gpt-4o-mini-tts`, `tts-1-hd` — verify current list).
- No explicit language parameter: the model infers from text. Bangla is **not** guaranteed —
  treat results as a capability test and expect higher CER on digits/code-mix.
- `instructions` (style prompt, gpt-4o-mini-tts only): empty in baseline. A variant may add
  "Speak in standard Bangladeshi Bangla" — label it as a variant.
- Output `response_format: "wav"` (or `pcm`, 24 kHz). TTFB via streaming response.
- Billing differs by model (per char vs per token) — set `price_unit` accordingly.
