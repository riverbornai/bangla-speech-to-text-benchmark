---
paths:
  - "runner/providers/azure.py"
  - "tests/providers/test_azure.py"
---
# Microsoft Azure AI Speech (Neural TTS)

- SDK: `azure-cognitiveservices-speech`. Secrets: `AZURE_SPEECH_KEY` and `AZURE_SPEECH_REGION`
  from Secret Manager (region is not secret but keep them together).
- Voices: confirm with the voices list REST endpoint
  (`https://<region>.tts.speech.microsoft.com/cognitiveservices/voices/list`) and filter
  `Locale in ("bn-BD","bn-IN")`. Expected bn-BD voices include `bn-BD-NabanitaNeural`
  (F) and `bn-BD-PradeepNeural` (M) — verify; don't trust this list blindly.
- Send SSML with `xml:lang="bn-BD"` and the voice name, with the text **XML-escaped**
  (`&`, `<`, `>` appear in edge-case rows). Escaping is required, not a "text trick".
- Output format: `Riff24Khz16BitMonoPcm`.
- TTFB: use `synthesizing` event (first chunk) on `SpeechSynthesizer`; total = `synthesis_completed`.
- Check `result.reason`; on `Canceled`, record `cancellation_details.error_details` (no key in logs).
- Pricing is per character, including SSML tags? → confirm on the pricing page and compute
  `billed_chars` the way Azure bills.
- Default concurrency limit depends on the tier (F0 is very low) — set `max_concurrency` to
  match the resource's tier; use S0 for benchmarks.
