# Hugging Face release

Two repos under the `riverborn` org:

| Repo | Type | Source folder |
|---|---|---|
| `riverborn/bangla-stt-benchmark-results` | Dataset | `hf/dist/results/` |
| `riverborn/bangla-stt-leaderboard` | Space (static) | `hf/dist/leaderboard/` |

Neither repo has audio or BanSpeech reference text.

## 1. Build

```bash
pip install pandas pyarrow huggingface_hub
python hf/build_hf_release.py
```

Open `hf/dist/leaderboard/index.html` in a browser and check it.

## 2. Log in

Make a token with **write** access to the `riverborn` org at
https://huggingface.co/settings/tokens, then:

```bash
hf auth login
```

## 3. Upload as private and check

```bash
hf repos create riverborn/bangla-stt-benchmark-results --repo-type dataset --private
hf upload riverborn/bangla-stt-benchmark-results hf/dist/results . --repo-type dataset --commit-message "Release v1.0"

hf repos create riverborn/bangla-stt-leaderboard --repo-type space --space-sdk static --private
hf upload riverborn/bangla-stt-leaderboard hf/dist/leaderboard . --repo-type space --commit-message "Release v1.0"
```

Check on the Hub:

- [ ] The Dataset Viewer shows every config (`leaderboard_batch` is the default).
- [ ] `load_dataset("riverborn/bangla-stt-benchmark-results", "leaderboard_batch", split="test")` works.
- [ ] The Space shows the leaderboard. Batch and Streaming tabs work. Hover tooltips work.
- [ ] The links on the Space page and the dataset card open.

## 4. Make public and tag

Set both repos to **Public** in each repo's Settings page. Then tag the dataset:

```bash
hf repos tag create riverborn/bangla-stt-benchmark-results v1.0 --repo-type dataset -m "Benchmark v1.0, tested September 2026"
```

## Upload without the CLI

You can also create both repos on huggingface.co and drag the files from
`hf/dist/results/` (keep the `data/` folder) and `hf/dist/leaderboard/` onto
each repo's "Upload files" page.

## 5. After release

- Make a collection "Bangla Speech-to-Text Benchmark" with the Space, the results dataset and `SUST-CSE-Speech/banspeech`.
- Add the HF links to the GitHub README, `CITATION.cff` and the riverborn.com research page.

## New benchmark version

Run the benchmark, then run `python hf/build_hf_release.py` again and upload
both folders. Add each new run ID to `MODELS` in `build_hf_release.py`.
Update the result tables in `hf/templates/dataset_card.md` by hand. Then tag
the new version (`v1.1`).
