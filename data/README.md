# Test set

`test_set.csv` is the fixed 1001-utterance test set every provider in this
benchmark was scored against: 77 randomly sampled utterances from each of the
13 flat BanSpeech domains (no dialect clips).

| column | meaning |
|---|---|
| `file_path` | BanSpeech path, e.g. `/audio_books/book_10_d_164.wav`; also the path under `wavs_1001/` after download |
| `domain` | one of the 13 BanSpeech domains |
| `ground_truth_transcription_bn` | human-annotated Bangla reference transcript, unmodified (normalization happens at scoring time) |

Only the transcripts are included here. The audio is **not** redistributed;
`python download_benchmark_audio.py` fetches exactly these clips from
Hugging Face.

## License

The transcripts in this folder, and the `ref` columns in
`results/per_file.csv` and `results/streaming_per_file.csv`, come from
**BanSpeech** ([`SUST-CSE-Speech/banspeech`](https://huggingface.co/datasets/SUST-CSE-Speech/banspeech)),
licensed **[CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/)**.
They are redistributed under the same license: attribution required,
non-commercial use only. This is separate from the MIT license that covers
the code in this repository.

If you use this test set, please cite BanSpeech as well as this benchmark.
