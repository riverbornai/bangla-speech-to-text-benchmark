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

This repository has **no audio and no reference transcripts**. They belong
to BanSpeech. To score a hypothesis again, or to listen to a clip, get it
from BanSpeech and join on `file_path` (see [Usage](#usage)).

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

## Method in short

- **Test set:** 1,001 clips from BanSpeech, 77 from each of its 13 domains. Clips are 3 seconds long on average, and 97% are less than 10 seconds.
- **Metrics:** CER (primary) and WER, after the same Bangla text normalization for all providers. Confidence intervals come from a bootstrap over clips.
- **Batch:** each clip is sent as one file.
- **Streaming:** audio is sent at real-time pace, like a live microphone.
- **Environment:** a laptop in Bangladesh on a regular internet connection.

The full method, the normalization rules and the limitations are in the
[interactive report](https://riverborn.com/research/bangla-speech-to-text-benchmark) and the [GitHub README](https://github.com/riverbornai/bangla-speech-to-text-benchmark#methodology).

## Limitations

- Results show each API as it behaved in September 2026. Vendors update models often. Run the benchmark again before you make a purchase decision.
- Latency includes the network distance from Bangladesh to each provider. It will be different from your location.
- Per-domain scores use 77 clips each. Treat small differences in one domain as ties.
- BanSpeech is public, so a provider can have trained on some of these clips. We cannot check this.

## License

This repository is released under **CC-BY-NC-4.0**, the same license as the
BanSpeech source data, because the hypotheses are transcripts of BanSpeech
audio. The benchmark code on GitHub is MIT.

## Citation

If you use these results, cite the benchmark and the BanSpeech dataset.

```bibtex
@misc{uddin2026banglastt,
  title        = {Bangla Speech-to-Text Benchmark: Hosted Bengali ASR APIs on BanSpeech},
  author       = {Uddin, Nasim and Azad, Saiful},
  year         = {2026},
  version      = {1.0.0},
  publisher    = {Riverborn Limited},
  howpublished = {\url{https://github.com/riverbornai/bangla-speech-to-text-benchmark}}
}
```

BanSpeech: [SUST-CSE-Speech/banspeech](https://huggingface.co/datasets/SUST-CSE-Speech/banspeech), SUST CSE Speech Group, CC-BY-NC-4.0.

## About Riverborn

[Riverborn Limited](https://riverborn.com) is an AI systems company in
Dhaka, Bangladesh. We build voice agents, LLM infrastructure and document
intelligence. Questions about this benchmark: [hello@riverborn.com](mailto:hello@riverborn.com).
