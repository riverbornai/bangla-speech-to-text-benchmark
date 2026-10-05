---
paths:
  - "runner/providers/sarvam.py"
  - "tests/providers/test_sarvam.py"
---
# Sarvam AI (Bulbul)

- Docs: https://docs.sarvam.ai/api-reference-docs/text-to-speech/convert — re-check models,
  speakers and limits before each round.
- Auth: header `api-subscription-key`, value from `SARVAM_API_KEY` in `.env`.
- SDK: `sarvamai` (`SarvamAI(api_subscription_key=...)`, `client.text_to_speech.convert(...)`),
  SDK retries disabled via `request_options={"max_retries": 0}`. Batch = `convert()` (base64 JSON, `ttfb_ms == total_ms`);
  stream = `convert_stream()` (raw bytes, POST /text-to-speech/stream, no request id).
- Language: `language_code="bn-IN"`. **bn-BD is not supported** — Indian Bengali accent is a
  known confound; the report must flag it (`bangla_support: bn-IN only`).
- Models: `bulbul:v3` (max 2500 chars, speaker default `shubh`, has `temperature`) and
  `bulbul:v2` (max 1500 chars, speakers anushka/manisha/vidya/arya/abhilash/karun/hitesh,
  has pitch/loudness). One model per run, from `config/providers.yaml`.
- Speakers are cross-lingual; pick one fixed speaker in providers.yaml.
- Output: `output_audio_codec=wav`, `speech_sample_rate=24000` (lossless, API defaults).
  Response JSON is `{"request_id", "audios": [base64...]}`; one input text → one audio.
- Text is sent unchanged, but per the SDK docs **bulbul:v3 always enables preprocessing**
  (server-side normalization) — note this next to Sarvam's scores.
  Leave pace/pitch/loudness/temperature at defaults; record any change in `voice_settings`.
- Rate limit: Starter 30 req/min for bulbul:v3 (Pro 200, Business 1000). 429 → backoff.
- Billing: per character in credits; price not published on the docs page — fill from the
  dashboard and set `price_checked`.
