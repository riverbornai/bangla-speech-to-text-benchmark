---
paths:
  - "runner/providers/**"
  - "config/providers.yaml"
---
# Provider contract (applies to every provider)

```python
@dataclass(frozen=True)
class SynthesisResult:
    audio: bytes
    format: str            # "wav" | "mp3" | "pcm" | "ogg"
    sample_rate: int
    ttfb_ms: float         # request sent -> first audio byte received (see "Latency metrics")
    total_ms: float        # request sent -> last audio byte received
    billed_chars: int
    request_id: str | None
    attempts: int

class TTSProvider(Protocol):
    name: str
    mode: Mode             # "batch" | "stream", from config.mode
    def supports(self, item: DatasetItem) -> bool: ...     # language/length checks
    format: str                                            # native file extension
    def synthesize(self, text: str) -> SynthesisResult: ...  # model + voice come from config
    def close(self) -> None: ...
```

Every provider module must:
1. Read model ID, voice, language code, output format, `max_chars`, and price **only** from `config/providers.yaml`.
2. Send `item.text` unchanged. No provider-side SSML tricks, text pre-normalization, or
   pronunciation dictionaries in the baseline run — we are measuring the model, not our fixes.
   (A separate `--variant tuned` run may add them; record that in run_config.json.)
3. Use the provider's **default** speed/pitch/style settings. Record any non-default value.
4. Prefer a 24 kHz (or higher) lossless output (WAV/PCM). If only MP3 is available, take the
   highest bitrate and note it — compressed audio slightly lowers UTMOS.
5. If input exceeds `max_chars`, mark `unsupported` — do not chunk silently (chunking changes
   long-form results). A chunked variant must be an explicit, labelled config.
6. Report `ttfb_ms` and `total_ms` for every request, as defined in "Latency metrics" below.
7. Have a test in `tests/providers/test_<name>.py` with a mocked HTTP response.
8. Use the provider's official Python SDK (pinned in `runner/requirements.txt`, imported lazily
   inside the provider module). Call the REST API directly only if no official SDK exists or
   the SDK lacks a needed feature; say why in a comment.

## Batch and stream modes (every provider implements both)
- Each provider is a package: `runner/providers/<name>/`
  - `_common.py`: shared client setup, `supports()`, request params, SDK error mapping, retries
  - `batch.py`: the non-streaming SDK method
  - `stream.py`: the streaming SDK method
  - `__init__.py`: `create(config)` picks the class from `config.mode`
- Choose the mode at run time with `--batch`, `--stream`, or both (both run batch first, then
  stream). With no flag, the mode is batch.
- Each mode writes its own `runs/<run_id>/<provider>/<model>/<voice>/<mode>/`. Never mix
  modes in one manifest.
- Both modes send the same text, model, voice, language and settings. A per-mode difference
  goes in an optional `batch:` or `stream:` block under the provider in `providers.yaml`, for
  example a codec the streaming endpoint requires. The difference is then recorded in
  `run_config.json`.
- If a provider has no streaming method, `stream` mode raises `ConfigError` at startup. Don't
  fall back to batch silently.

## Latency metrics (TTFB and RTF, required for every model and mode)
- **Clock:** use `time.perf_counter_ns()`. Start the clock just before the SDK call, after the
  client is built and the text is prepared. Time only the attempt that succeeded: reset the clock
  on every retry, and never include backoff sleeps.
- **TTFB** (`ttfb_ms`) is the time until the first non-empty audio chunk arrives. Use
  `base.collect_chunks()` for any chunk iterator.
  - **stream:** the server sends audio while it renders, so this is time to first audio and the
    real latency number.
  - **batch:** the server renders the whole clip before sending, so TTFB is about the same as
    `total_ms`. If the SDK returns one body (for example Sarvam base64 JSON), set
    `ttfb_ms = total_ms`.
- **Audio duration** (`audio_seconds`) is measured from the returned audio, never estimated from text:
  - wav: from the header (`wave` module), falling back to `ffprobe`
  - pcm: `bytes / (sample_rate * 2 * channels)`
  - mp3, ogg and flac: `ffprobe`, which ships in the image with ffmpeg
- **RTF** is `(total_ms / 1000) / audio_seconds`. Lower is better, and below 1 means faster than
  real time. The runner computes it, not the provider module, so the formula is the same everywhere.
- **Manifest:** every `ok` row writes `mode`, `ttfb_ms`, `total_ms`, `audio_seconds` and `rtf`.
  If the duration can't be measured, fail that item; don't write `rtf: null`.
- **Context:** record the job region and machine (cpu/memory, or GPU type for self-hosted models)
  in `run_config.json`, because network distance to the provider is part of TTFB. Self-hosted models
  measure the same way, with model load and warm-up excluded. Do one warm-up call and don't record it.
- **Reporting:** report p50, p90 and mean per model and mode, overall and per category. Compare
  TTFB only within the same mode. RTF can be compared across modes.
