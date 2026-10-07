---
paths:
  - "runner/providers/elevenlabs.py"
  - "tests/providers/test_elevenlabs.py"
---
# ElevenLabs

**User override (2026-10-02), takes precedence over the bullets below:** use the official SDK
`text_to_speech.convert()`, `output_format=mp3_44100_128`, and `voice_settings` stability 0.1 /
similarity_boost 0.75 (set in `config/providers.yaml`). Batch = `text_to_speech.convert()`, stream = `text_to_speech.stream()` (same params); RTF uses the
ffprobe mp3 duration. Do not revert.

- API key: `ELEVENLABS_API_KEY` in `.env`. Docs: https://elevenlabs.io/docs/overview/models
- Model IDs: get from `GET /v1/models` and pick the ones that list Bengali (`ben` / `bn`).
  Candidates: Eleven v4, Eleven v4 Turbo, Eleven v3, Multilingual v2. Do not guess IDs.
- Pass `language_code` (ISO 639-1, `bn`) when the model supports it, to stop auto-detection
  flipping to Hindi on short or digit-heavy inputs. Record whether it was set.
- Voices: ElevenLabs voices are language-agnostic. Use two fixed library voice IDs (one F,
  one M) for all items, chosen once and stored in providers.yaml. Note that voice choice
  heavily affects Bangla accent quality — this is a known confound.
- Output: `output_format=pcm_24000` (or `pcm_44100` if the plan allows). MP3 only as fallback.
- TTFB: first chunk from `stream()` in stream mode; `null` in batch mode (see the contract's "Latency metrics").
- Leave `voice_settings` at defaults. Text normalization parameter (`apply_text_normalization`)
  at its default for baseline; test `on` as a separate variant.
- Concurrency is capped per subscription tier → set `max_concurrency` from the plan; on 429
  back off, don't fail.
- Billing is per character (credits) — record the plan's effective $/1M chars.
