---
paths:
  - "runner/providers/gemini/**"
  - "tests/providers/test_gemini.py"
---
# Gemini-TTS (google-genai, Vertex / enterprise)

- Docs: https://docs.cloud.google.com/text-to-speech/docs/gemini-tts and
  https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash-tts — re-check the model list
  before each round; models move from Preview to GA. (Read 2026-10-07: the Cloud TTS page did not
  yet list `gemini-3.8-flash-tts`; the model page does.)
- SDK: `google-genai` (pinned in `runner/requirements.txt`), `Client(enterprise=True, project, location)`.
  Auth via ADC (job service account). **No API key, no `.env` entry.** Project comes from
  `GOOGLE_CLOUD_PROJECT` or the ADC project; location from `location:` in providers.yaml (`global`).
  (The old rule said `google-cloud-texttospeech`; that SDK is not used.)
- Calls: batch = `models.generate_content`, stream = `models.generate_content_stream`, both with
  `response_modalities=["AUDIO"]` and `speech_config.voice_config.voice = <voice id>`.
- Language: the model detects it from the text; we still send `speech_config.language_code=bn-BD`
  (listed GA for Gemini-TTS). VERIFY the 3.8 model accepts it; if it rejects it, drop it.
- Style: dataset text may contain `[style]` tags at the start of a sentence (e.g. `[laugh] ...`).
  `styles.build_parts` splits the text into `Part`s: each tag becomes `speech_metadata.style` on the
  text up to the next tag; untagged sentences stay in plain parts. A tag is always a single English word (Latin letters only), so anything else, such as a
  Bangla `[বিজ্ঞপ্তি]` stays text. Tag names are passed verbatim (no mapping), and `billed_chars` is the
  original text length. With no tags the request is a single plain part (the baseline).
- Output: the model returns WAV (RIFF) at 24 kHz; `_common.to_wav` re-wraps whatever arrives
  (RIFF or headerless L16) into a WAV with a correct header, since streamed chunks are concatenated.
- Limits: 8192 input tokens. The Cloud TTS API limits text to 4000 *bytes* (≈1300 Bangla chars);
  `max_chars` is 4000 chars and unverified for the genai route.
- Safety/empty responses surface as `empty_audio` (a failed item), never as silent audio.
- Billing: token-based; price still `VERIFY` in providers.yaml (`billed_chars` is input chars only).
- Benchmark at least one female (Kore) and one male (Charon) voice as separate configs.
