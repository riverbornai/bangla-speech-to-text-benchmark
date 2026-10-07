---
paths:
  - "runner/providers/soniox/**"
  - "tests/providers/test_soniox.py"
---
# Soniox TTS

Docs: https://soniox.com/docs/tts/get-started, API reference https://soniox.com/docs/api-reference/tts/generate_tts
(read 2026-10-07). SDK: `soniox` (pinned in `runner/requirements.txt`), imported lazily.

- Auth: `SONIOX_API_KEY` in `.env`. The SDK would also read it from the environment, but `create()` passes it explicitly.
- Language: `bn` (officially supported). `bn-BD` is not documented. There is no auto-detect: always send `language`.
- Model: `tts-rt-v2`. `tts-rt-v1` is deprecated and the REST default is still v1, so the model is always passed.
- Voice: by name (`Adrian` is from the official examples). Every voice works in every language, so there are no
  Bengali-specific voices; per-voice Bengali quality is undocumented. List them with `GET /v1/tts-models`.
- Batch: `client.tts.generate(text, voice, model, language, config=CreateTtsConfig(audio_format="wav", sample_rate=24000))`
  -> `POST https://tts-rt.soniox.com/tts`, JSON body `model, language, voice, audio_format, sample_rate, text`,
  returns the audio bytes. `audio_format`/`sample_rate` as direct kwargs are deprecated: use `CreateTtsConfig`.
- Stream: `client.realtime.tts.connect(config=RealtimeTTSConfig(...))` (WebSocket, one connection per item). The
  whole text goes out in one `send_text_chunk(text, text_end=True)`, then `receive_audio_chunks()` yields decoded
  bytes until the server's `terminated`. Streams `pcm_s16le` @ 24 kHz; the runner wraps it with `base.pcm_to_wav`
  (a streamed WAV header is unverified). `output_format: pcm_24000` comes from the `stream:` block in providers.yaml.
- TTFB: the clock starts right before `send_text_chunk`, after the socket is open, so the WebSocket handshake is
  excluded (HTTP providers reuse pooled connections). TTFB = first non-empty audio chunk. Batch TTFB is `null`.
- Formats: wav, flac, mp3, opus, aac, pcm_f32le, pcm_s16le, pcm_mulaw, pcm_alaw. Sample rates 8000, 16000, 24000,
  44100, 48000 (PCM/WAV default 24000). Baseline sends no `speed` or `reduce_silence`.
- Limits: 5000 characters per REST request (`max_chars`), audio capped at 2 minutes (truncated on REST, an error on
  WebSocket). 100 requests/min and 3 concurrent; the runner is sequential.
- Retries: the SDK does not retry, so `with_retries` owns it (429/5xx/transport only, 5 attempts).
- Errors: REST failures raise `SonioxAPIError` subclasses: 400 invalid request, 401/403 authentication, 404, 409,
  429 rate limit, 5xx server; **402, 408 and any other status raise the plain `SonioxAPIError`**. Log only
  `api_error.error_type` (e.g. `limit_exceeded`, `organization_balance_exhausted`), never the message. A non-JSON error
  body leaves `api_error` empty (message becomes `http_<status>`). `Retry-After` is not read by the SDK; we read it
  from `error.response.headers`. Realtime failures raise `SonioxRealtimeError` with only a message: server errors end
  in `(code N)` and become that status; timeouts and disconnects have no code and are retried as transport errors.
- Request id: error bodies carry `request_id` (`SonioxAPIError.request_id`). Success returns plain bytes or audio
  events, so `request_id` is `None` on success (we do not invent one).
- Tags (emotive variant, `config/soniox.json`): bracketed English tags before the text they affect, e.g. `[laughs]`,
  `[sighs]`, `[pause]`, `[long pause]`, `[whispering]`, `[shouting]`. Whether they work with Bengali text is undocumented.
- Billing is token-based, not per character: text input $4.00 / 1M tokens (~0.3 tokens per character), audio output
  $21.50 / 1M tokens (~$0.70 per hour of speech). Bengali tokenisation is unverified, so `est_cost_usd` stays null
  (`price.unit: VERIFY` in providers.yaml). `billed_chars` is the input character count.
