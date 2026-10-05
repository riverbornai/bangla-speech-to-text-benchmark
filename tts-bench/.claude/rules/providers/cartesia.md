---
paths:
  - "runner/providers/cartesia.py"
  - "tests/providers/test_cartesia.py"
---
# Cartesia Sonic

- Secret: `CARTESIA_API_KEY`. Every request needs the `Cartesia-Version` header — pin the
  version string in providers.yaml.
- Model: Sonic 3.x (`model_id` from the docs/models list; e.g. `sonic-3`). `language: "bn"`.
- Voice: requires a `voice` id. Prefer a voice Cartesia marks as Bengali; otherwise a
  multilingual voice. Store the id and the reason in providers.yaml.
- Non-streaming: `POST /tts/bytes` with `output_format: {container: "wav", encoding:
  "pcm_s16le", sample_rate: 24000}`. TTFB: use the WebSocket or SSE endpoint.
- Cartesia's selling point is latency: run a separate latency-only pass from a region close
  to their API, with concurrency 1, so numbers are comparable.
- Rate limits per plan → `max_concurrency` in config.
