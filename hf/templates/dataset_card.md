---
pretty_name: Bangla Speech-to-Text Benchmark Results
language:
  - bn
license: cc-by-nc-4.0
task_categories:
  - automatic-speech-recognition
size_categories:
  - 10K<n<100K
source_datasets:
  - SUST-CSE-Speech/banspeech
tags:
  - benchmark
  - leaderboard
  - asr
  - speech-to-text
  - stt
  - bangla
  - bengali
  - streaming
  - evaluation
configs:
  - config_name: leaderboard_batch
    default: true
    data_files:
      - split: test
        path: data/leaderboard_batch.parquet
  - config_name: leaderboard_streaming
    data_files:
      - split: test
        path: data/leaderboard_streaming.parquet
  - config_name: by_domain
    data_files:
      - split: test
        path: data/by_domain.parquet
  - config_name: batch_predictions
    data_files:
      - split: test
        path: data/batch_predictions.parquet
  - config_name: streaming_predictions
    data_files:
      - split: test
        path: data/streaming_predictions.parquet
  - config_name: pairwise
    data_files:
      - split: test
        path: data/pairwise.parquet
  - config_name: clips
    data_files:
      - split: test
        path: data/clips.parquet
---

# Bangla Speech-to-Text Benchmark: Results

Results of an open benchmark of **8 hosted Bangla (Bengali) speech-to-text
APIs** on **1,001 real audio clips** across **13 domains**, in **batch** and
**real-time streaming** mode. Tested in **September 2026**.

- 📈 **Interactive report:** [riverborn.com/research/bangla-speech-to-text-benchmark](https://riverborn.com/research/bangla-speech-to-text-benchmark)
- 🏆 **Leaderboard:** [riverborn/bangla-stt-leaderboard](https://huggingface.co/spaces/riverborn/bangla-stt-leaderboard)
- 💻 **Code, method and full report:** [github.com/riverbornai/bangla-speech-to-text-benchmark](https://github.com/riverbornai/bangla-speech-to-text-benchmark)
- 🎧 **Audio and reference text:** [SUST-CSE-Speech/banspeech](https://huggingface.co/datasets/SUST-CSE-Speech/banspeech)
- 🏢 **Research by:** [Riverborn Limited](https://riverborn.com), Dhaka, Bangladesh
- 🔖 **DOI (all versions):** [10.5281/zenodo.22946242](https://doi.org/10.5281/zenodo.22946242)

This repository has **no audio and no reference transcripts**. They belong
to BanSpeech. To score a hypothesis again, or to listen to a clip, get it
from BanSpeech and join on `file_path` (see [Usage](#usage)).

## The short answer

- **Most accurate for recorded audio:** Sarvam AI (`saarika:v2.5`) at 6.9% CER.
- **Most accurate for live streaming:** Soniox (`stt-rt-v5`) at 7.4% CER.
- **Cheapest:** Soniox at $0.10 per audio hour (batch), with the second-best accuracy.
- **Fastest live transcript:** Sarvam AI. The final text arrives 0.9 s after the speaker stops (median).

## Key findings

1. **Bangla specialists win.** Sarvam (6.9%) and Soniox (8.1%) lead batch, and change places in streaming. The gap between them is small, but statistically real (paired bootstrap).
2. **Live can beat batch.** The Soniox real-time model (7.4%) was more accurate than its own batch model (8.1%).
3. **Big global names trail.** OpenAI `gpt-4o-transcribe` (28.7%) and Whisper large-v3 (30.7%) make 4 to 5 times the errors of the leaders on Bangla.
4. **Domain matters a lot.** ElevenLabs Scribe is mid-table overall (14.7%), but it gets 47.1% CER on medicine and less than 10% on audiobooks and TV news.
5. **Cheapest is near the top.** Soniox batch costs $0.10 per audio hour, one tenth of Google Chirp 2, and has the second-best accuracy.
6. **Streaming latency varies 5×.** After the speaker stops, Sarvam gives the final transcript in 0.9 s (median). OpenAI takes 4.2 s and Gemini Live takes more than 10 s.

## Results

Lower is better. **CER** (character error rate) is the primary metric.
Brackets show 95% bootstrap confidence intervals.

### Batch (whole-file transcription)

| # | Provider | Model | CER | WER | Mean latency | List price / hour |
|---|---|---|---|---|---|---|
| 1 | Sarvam AI | `saarika:v2.5` | **6.9%** [6.2–7.5] | **18.2%** | 0.99 s | $0.31 |
| 2 | Soniox | `stt-async-v5` | 8.1% [7.3–9.0] | 21.5% | 7.58 s | $0.10 |
| 3 | Deepgram | `nova-3` | 10.1% [9.2–11.1] | 23.9% | 2.15 s | $0.26 |
| 4 | Google Gemini | `gemini-2.5-flash` | 13.3% [12.2–14.5] | 27.0% | 3.85 s | at least $0.12 |
| 5 | ElevenLabs | `scribe_v1` | 14.7% [13.3–16.1] | 26.0% | 1.39 s | $0.22 |
| 6 | Google Cloud | `chirp_2` | 21.9% [19.9–24.1] | 41.4% | 4.13 s | $0.96 |
| 7 | OpenAI | `gpt-4o-transcribe` | 28.7% [26.4–31.1] | 45.1% | 1.11 s | $0.36 |
| 8 | Groq | `whisper-large-v3` | 30.7% [29.2–32.4] | 71.7% | 0.66 s | $0.11 |

### Streaming (audio sent at real-time pace)

| # | Provider | Model | CER | WER | First partial (p50) | Final after speech ends (p50) | List price / hour |
|---|---|---|---|---|---|---|---|
| 1 | Soniox | `stt-rt-v5` | **7.4%** [6.5–8.3] | **19.7%** | 1.85 s | 2.46 s | $0.12 |
| 2 | Sarvam AI | `saaras:v3-realtime` | 9.0% [7.8–10.3] | 20.3% | 1.35 s | 0.88 s | $0.31 |
| 3 | Deepgram | `nova-3` | 17.5% [16.3–18.7] | 33.3% | 2.33 s | 1.55 s | $0.46 |
| 4 | Google Cloud | `chirp_2` | 23.6% [21.5–25.8] | 43.8% | 7.15 s | 2.17 s | $0.96 |
| 5 | OpenAI | `gpt-4o-transcribe` (Realtime API) | 24.6% [22.1–27.1] | 42.4% | 3.60 s | 4.22 s | $0.36 |
| 6 | ElevenLabs | `scribe_v2_realtime` | 38.6% [35.9–41.3] | 55.4% | 3.13 s | 1.36 s | $0.39 |
| 7 | Google Gemini | `gemini-2.5-flash-native-audio-preview-12-2025` (Live API) | 69.6% [67.7–71.4] | 79.2% | n/a | 10.44 s | at least $0.35 |

Latency was measured from Bangladesh and includes network time. Prices are
pay-as-you-go list prices in USD, checked on 24 September 2026. The sources
for each price are in [`prices.yaml`](prices.yaml).

## Configs

| Config | Rows | Contents |
|---|---|---|
| `leaderboard_batch` | 8 | CER and WER with 95% CI, coverage, latency, real-time factor, list and effective price |
| `leaderboard_streaming` | 7 | Same as batch, plus time to first partial, time to first final, finalization latency, partial-result stability |
| `by_domain` | 195 | CER for each provider, mode and domain (13 domains, 77 clips each) |
| `batch_predictions` | 8,006 | Each clip and provider: hypothesis text, CER, WER |
| `streaming_predictions` | 6,996 | Each clip and provider: hypothesis text, CER, WER, latency per clip, number of partial and final results |
| `pairwise` | 13 | Paired bootstrap comparison between providers (CER gap with 95% CI and probability that A is better) |
| `clips` | 1,001 | The test set: BanSpeech `file_path` and domain |

The `run_id` column is the model key in the GitHub code. The `provider` and
`model_id` columns name the exact API model that we tested.

## Usage

Load a leaderboard:

```python
from datasets import load_dataset

batch = load_dataset("riverborn/bangla-stt-benchmark-results", "leaderboard_batch", split="test")
print(batch.to_pandas()[["rank", "provider", "model_id", "cer", "wer"]])
```

Join the predictions with the BanSpeech references:

```python
import pandas as pd
from datasets import load_dataset

preds = load_dataset("riverborn/bangla-stt-benchmark-results", "batch_predictions", split="test").to_pandas()

# BanSpeech stores each domain as a split. Load only the text columns.
banspeech = load_dataset("SUST-CSE-Speech/banspeech")
refs = pd.concat(
    [banspeech[split].remove_columns("audio").to_pandas() for split in banspeech],
    ignore_index=True,
)

joined = preds.merge(refs[["file_path", "transcription"]], on="file_path", how="left")
print(joined[["provider", "file_path", "transcription", "hypothesis", "cer"]].head())
```

To transcribe the audio yourself and add a provider, use the scripts in the
[GitHub repository](https://github.com/riverbornai/bangla-speech-to-text-benchmark#reproduce-it).

## Method

### Test set

1,001 clips from [BanSpeech](https://huggingface.co/datasets/SUST-CSE-Speech/banspeech)
(SUST CSE Speech Group), 77 sampled at random from each of its 13 domains.
Regional dialect clips are not included. Clips are 16 kHz WAV, 0.7 s to
26.8 s long (median 2.1 s), 50.0 minutes in total, with 7,996 reference
words and 43,411 characters. 97% of clips are shorter than 10 seconds, like
voice commands and conversation turns.

| Domain | Clips | Minutes | Mean length | Words |
|---|---|---|---|---|
| Audiobooks | 77 | 2.2 | 1.7 s | 409 |
| Biography | 77 | 3.0 | 2.3 s | 396 |
| Celebrity interview | 77 | 5.2 | 4.1 s | 854 |
| Class lecture | 77 | 5.0 | 3.9 s | 943 |
| Documentary | 77 | 3.1 | 2.4 s | 457 |
| Drama series | 77 | 4.4 | 3.4 s | 774 |
| Kids' cartoon | 77 | 3.4 | 2.7 s | 524 |
| Kids' voices | 77 | 6.5 | 5.0 s | 947 |
| Medicine | 77 | 3.5 | 2.7 s | 481 |
| Parliament | 77 | 3.9 | 3.0 s | 596 |
| Political talk show | 77 | 3.0 | 2.4 s | 498 |
| Sports | 77 | 3.3 | 2.6 s | 586 |
| TV news | 77 | 3.4 | 2.6 s | 531 |
| **Total** | **1,001** | **50.0** | **3.0 s** | **7,996** |

### Metrics

- **CER (primary):** character substitutions, deletions and insertions that change the transcript into the reference, divided by the reference length. **WER** is the same at word level.
- **Corpus-level:** total edits across all clips divided by total reference length, not an average of per-clip rates.
- **Why CER:** Bangla word spacing is not consistent between annotators and engines. One spacing difference counts as two word errors even when every letter is correct, so WER is much higher than CER for every provider.
- **Confidence intervals:** 10,000 bootstrap resamples of the clips. Comparisons between providers use a paired bootstrap over the clips that both transcribed (`pairwise` config).
- **Coverage:** a failed request is not included in the score of that provider. It is not counted as 100% error. Every provider covered at least 99.4% of the clips.

### Text normalization

The same normalizer runs on the references and on every transcript before
scoring ([`src/normalize.py`](https://github.com/riverbornai/bangla-speech-to-text-benchmark/blob/main/src/normalize.py)):
Unicode NFC, remove zero-width characters (ZWNJ, ZWJ, BOM), map Bangla
digits ০–৯ to 0–9, replace punctuation (including the danda ।) with a space,
lowercase Latin text, then collapse whitespace. The `hypothesis` column has
the raw provider output, before normalization.

### Setup

- **Batch:** one request for each clip, one at a time. Latency is the wall-clock request time.
- **Streaming:** 16-bit PCM in 100 ms chunks. Each chunk is sent only after that much real time has passed, like a live microphone. Accuracy is scored on the final transcript, so batch and streaming are directly comparable.
- **Settings:** provider defaults, except for the language. No custom vocabulary and no fine-tuning. Only Gemini batch received a prompt ("Transcribe this Bengali (Bangla) audio verbatim...").
- **Environment:** a MacBook in Bangladesh on a regular internet connection. Provider servers were in the US, Europe or India. Google Chirp 2 ran in `us-central1`.

### Models and language settings

| Provider | Batch model | Streaming model | Language |
|---|---|---|---|
| Sarvam AI | `saarika:v2.5` | `saaras:v3-realtime` | `bn-IN` |
| Soniox | `stt-async-v5` | `stt-rt-v5` | hint `bn` |
| Deepgram | `nova-3` | `nova-3` | `bn` |
| Google Gemini | `gemini-2.5-flash` | `gemini-2.5-flash-native-audio-preview-12-2025` (Live API) | named in prompt (batch), auto-detect (streaming) |
| ElevenLabs | `scribe_v1` | `scribe_v2_realtime` | `ben` |
| Google Cloud STT v2 | `chirp_2` | `chirp_2` | `bn-BD` |
| OpenAI | `gpt-4o-transcribe` | `gpt-4o-transcribe` (Realtime API) | `bn` |
| Groq | `whisper-large-v3` | none | `bn` |

### Pricing notes

- **Groq** bills at least 10 seconds for each request. On these short clips, it costs 3.4× its list price.
- **Sarvam** and **Google** round each request up to the next second. This adds about 17% on these clips.
- **Soniox real-time** bills the streaming session time, which includes the wait for the final transcript. This adds about 40% on these clips.
- **Sarvam** prices in rupees, converted at ₹95.96 per US$ (ECB reference rate, 24 September 2026).
- Token-billed prices (Soniox, OpenAI) are estimates. Gemini prices are minimums, because they include only the audio input.

## Limitations

- A snapshot of these APIs in September 2026. Providers update their models often. Run the benchmark again before you make a purchase decision.
- Mostly read and broadcast speech. No phone audio, heavy noise, regional dialects or Bangla-English code-switching.
- Language tags are different for each provider (`bn`, `bn-IN`, `bn-BD`, `ben`). This can have an effect on the results.
- Gemini Live returned no interim transcripts, and its adapter set no language hint.
- ElevenLabs batch requested `scribe_v1`, which was scheduled for removal. Every request succeeded, so we cannot tell which version served them.
- Latency includes the network distance from Bangladesh to each provider. It will be different from your location.
- Per-domain scores use 77 clips each. Treat small differences in one domain as ties.
- Only hosted APIs were tested. Self-hosted open-weight models are not included in v1.0.

## Conflict of interest

Riverborn Limited funded and ran this benchmark, and paid for all API usage.
We have no commercial relationship with any provider that we tested: we are
not a partner, reseller or investor of any of them. No provider sponsored or
reviewed this benchmark before publication. All code, prompts, settings,
transcripts and scores are public, so anyone can check the results.

## License

This repository is released under **CC-BY-NC-4.0**, the same license as the
BanSpeech source data, because the hypotheses are transcripts of BanSpeech
audio. The benchmark code on GitHub is MIT.

## Citation

If you use these results, cite the benchmark and the BanSpeech dataset.
DOI (all versions): [10.5281/zenodo.22946242](https://doi.org/10.5281/zenodo.22946242).

```bibtex
@software{riverborn2026banglastt,
  title     = {Bangla Speech-to-Text Benchmark: Hosted Bengali ASR APIs on BanSpeech},
  author    = {Uddin, Nasim and Azad, Saiful},
  publisher = {Zenodo},
  year      = {2026},
  doi       = {10.5281/zenodo.22946242},
  url       = {https://doi.org/10.5281/zenodo.22946242}
}
```

BanSpeech: [SUST-CSE-Speech/banspeech](https://huggingface.co/datasets/SUST-CSE-Speech/banspeech), SUST CSE Speech Group, CC-BY-NC-4.0.

## About Riverborn

[Riverborn Limited](https://riverborn.com) is an AI systems company in
Dhaka, Bangladesh. We build voice agents, LLM infrastructure and document
intelligence. Questions about this benchmark: [hello@riverborn.com](mailto:hello@riverborn.com).
