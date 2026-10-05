---
paths:
  - "runner/providers/gemini.py"
  - "tests/providers/test_gemini.py"
---
# Gemini-TTS (Google Cloud Text-to-Speech)

- Docs: https://cloud.google.com/text-to-speech/docs/gemini-tts — re-check the model list and
  language table before each benchmark round; models move from Preview to GA.
- SDK: `google-cloud-texttospeech` (docs require ≥ 2.29.0 for Gemini-TTS). Auth via ADC
  (job service account). **No API key, no Secret Manager entry.**
- Language: `language_code="bn-BD"` (listed GA). Do not use `bn-IN` unless running the
  accent comparison variant.
- Model goes in `voice.model_name` (e.g. `gemini-2.5-flash-tts`, `gemini-2.5-pro-tts`,
  preview models such as `gemini-3.1-flash-tts-preview`). Voice = prebuilt speaker name
  (e.g. `Kore`, `Charon`). Benchmark at least one female and one male voice.
- `prompt` field (style instruction): leave **empty** for the baseline run. A styled variant is
  a separate config entry.
- Output: `LINEAR16` at 24 kHz for unary; for TTFB use the streaming method (PCM chunks).
- Regions: Preview models may be `global`-only — use the endpoint the docs list for the model.
- Also benchmark Chirp 3 HD voices **only if** `list_voices(language_code="bn-BD")` returns
  any; otherwise mark them `unsupported` in the report rather than silently using `bn-IN`.
- Billing is per input token/character depending on model — confirm unit on the pricing
  page and set `price_unit` accordingly in providers.yaml.
