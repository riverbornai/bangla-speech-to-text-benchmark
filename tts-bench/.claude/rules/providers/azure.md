---
paths:
  - "runner/providers/azure.py"
  - "tests/providers/test_azure.py"
---
# Microsoft Azure AI Speech (Neural TTS)

- Called over the **REST API with httpx**, not the `azure-cognitiveservices-speech` SDK (a deliberate
  exception to contract rule 8, explained in the module docstring): one SSML POST per item to
  `https://<region>.tts.speech.microsoft.com/cognitiveservices/v1`.
- Secrets in `.env`: `AZURE_SPEECH_KEY` and `AZURE_SPEECH_REGION`. A `User-Agent` header is required.
- Voices (docs read 2026-10-12): bn-BD has `bn-BD-NabanitaNeural` (F) and `bn-BD-PradeepNeural` (M),
  both Standard/Neural. No styles or roles are listed, so there is no `mstts:express-as`; phonemes,
  lexicons and visemes are unsupported. Benchmark both as separate configs.
- SSML: `<speak version="1.0" xml:lang="bn-BD"><voice name=...>`; the text is **XML-escaped**
  (required, not a "text trick"), except `<break time="..."/>` pauses from the emotive variant
  (`config/azure.json`: short_pause 300ms, pause 700ms, long_pause 1.5s; other tags are removed).
- Output: `X-Microsoft-OutputFormat` `riff-24khz-16bit-mono-pcm` (also 48 kHz). No documented 16 kHz
  riff format. The riff header may not be final, so the runner always re-wraps via `base.to_wav`.
- TTFB: stream mode reads the same response with `iter_bytes()`; whether Azure sends chunked audio
  for riff formats is undocumented, so TTFB may be close to `total_ms` (check on a real run).
- Errors: 400/401/415/429/502/503 documented. The response body is never kept. No retries; most 429s
  on standard voices are backend capacity, not quota, so expect some at S0 (30 TPS) and more at F0
  (20 requests/min). The request-id header name (`x-requestid`) is undocumented: verify.
- Billing: per character of the SSML including markup except `<speak>`/`<voice>`, whitespace
  included. `billed_chars` is `len(text)` (the text as sent, break tags included, before escaping).
  Price still `VERIFY` (the quotas page uses $15 / 1M characters in an example only).
- Limits: audio is truncated at 10 minutes; no documented REST text limit (`max_chars: 5000` is a guess).
