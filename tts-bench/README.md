# Bangla TTS Benchmark

Synthesizes every row of the dataset workbook with one TTS provider, then records latency,
real-time factor, and cost for each clip. You can run it on Cloud Run or on your own machine.

| Provider | Model | Voice | Output | Batch | Stream |
|---|---|---|---|---|---|
| `elevenlabs` | `eleven_v4` (`bn`) | george | mp3 44.1 kHz 128k | `convert()` | `stream()` |
| `sarvam` | `bulbul:v3` (`bn-IN` only) | shubh | wav 24 kHz | `convert()` | `convert_stream()` |

Model IDs, voices and formats are set only in `config/providers.yaml`.

## What a run produces

```
runs/<run_id>/<provider>/<model>/<voice>/<batch|stream>/
  <item_id>.<ext>       raw provider audio, untouched
  manifest.jsonl        one line per dataset row
  run_config.json       config, dataset info, region/cpu/memory
```

Each `ok` row in `manifest.jsonl` has:

| Field | Meaning |
|---|---|
| `total_ms` | Request sent → last audio byte (only the attempt that succeeded) |
| `ttfb_ms` | **stream mode only**: request sent → first audio byte. `null` in batch mode |
| `audio_seconds` | Duration measured from the audio (wav header, or `ffprobe` for mp3) |
| `rtf` | `total_ms / 1000 / audio_seconds`. Lower is better; below 1 is faster than real time |
| `est_cost_usd` | `billed_chars` × price from `providers.yaml`; empty while the price is `VERIFY` |

Other statuses:
- `error`: the request failed. Nothing is retried; the error status is recorded and the run continues.
- `unsupported`: the text is longer than `max_chars`.
- `skipped_existing`: the audio is already on disk.

## CLI

```
python -m runner.main --provider <elevenlabs|sarvam> [--batch] [--stream]
                      [--run-id ID] [--limit N] [--dataset PATH] [--out DIR]
```

| Flag | Default | Notes |
|---|---|---|
| `--provider` | required | A key in `config/providers.yaml` |
| `--batch` / `--stream` | batch | Pass both to run batch, then stream, into separate folders |
| `--run-id` | `YYYYMMDD-HHMM-<git sha>` | Reuse an ID to **resume**: existing audio is skipped and not billed again |
| `--limit` | all rows | Takes the first N rows sorted by `id`. Use `--limit 5` for smoke tests |
| `--dataset` | `$DATASET_PATH` | Path to the `.xlsx` file (sheet `Dataset`) |
| `--out` | `$AUDIO_ROOT` | Root folder for the `runs/` output |
| `--max-error-rate` | `0.2` | Exit code is 1 if more than this share of items fail |

## API keys

Put the keys in `tts-bench/.env`. The file is gitignored and is never committed:

```
ELEVENLABS_API_KEY=...
SARVAM_API_KEY=...
```

The runner loads `.env` itself, and real environment variables take precedence. `.env` is
also copied into the Docker image, so anyone who can pull the image can read the keys.
Keep the Artifact Registry repo private, and rebuild the image after you change a key.

---

## Run locally

### Option A: Python

Requires Python 3.12. You also need `ffmpeg` (for `ffprobe`) to measure mp3 durations; without
it, mp3 items fail with `audio_duration_unmeasurable`. On macOS, install it with `brew install ffmpeg`.

```bash
cd tts-bench
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

mkdir -p local/audio
cp bangla_tts_benchmark_dataset_v0.1.xlsx local/dataset.xlsx

# 5-row smoke test, both modes
python -m runner.main --provider elevenlabs --batch --stream --limit 5 \
  --dataset local/dataset.xlsx --out local/audio
```

The output goes to `local/audio/runs/...`, and `local/` is gitignored.

### Option B: Docker (same image as Cloud Run)

```bash
cd tts-bench
docker build --platform linux/amd64 -f runner/Dockerfile -t tts-runner:local .

docker run --rm --platform linux/amd64 \
  -v "$PWD/local:/data" \
  tts-runner:local \
  --provider sarvam --stream --limit 5 \
  --dataset /data/dataset.xlsx --out /data/audio
```

On macOS, Docker Desktop must be allowed to share the folder you mount: Settings →
Resources → File sharing. If the repo is somewhere Docker can't share, such as
`/Applications`, mount a copy from your home folder instead.

### Tests and lint

```bash
pytest -q                               # every provider HTTP call is mocked; no paid APIs
ruff check . && ruff format --check .
```

---

## Run on Cloud Run

These are the existing resources in project `connekt-studio`, region `asia-south1` (Mumbai):

| Resource | Name |
|---|---|
| Bucket | `gs://test-ml-nasim`, with everything under `tts-bench/` |
| Dataset | `gs://test-ml-nasim/tts-bench/dataset/bangla_tts_benchmark_dataset_v0.1.xlsx` |
| Images | `asia-south1-docker.pkg.dev/connekt-studio/cloud-run-source-deploy/tts-runner:<tag>` |
| Job | `tts-runner-dev`: one generic job for every provider, created by Terraform |
| Service account | the default compute SA |

The job mounts the bucket twice: read-only at `/mnt/dataset` and read-write at `/mnt/audio`.
`DATASET_PATH` and `AUDIO_ROOT` are set on the job, so you only pass the per-run arguments.

Use the account that has access:

```bash
gcloud config set account mr.saiful.azad@gmail.com
gcloud config set project connekt-studio
```

### 1. Upload the dataset (once, or when it changes)

```bash
gcloud storage cp bangla_tts_benchmark_dataset_v0.1.xlsx \
  gs://test-ml-nasim/tts-bench/dataset/
```

### 2. Build and push the image

Run this whenever the code, `config/providers.yaml` or `.env` changes. Cloud Build runs the
tests and then builds and pushes the image:

```bash
cd tts-bench
gcloud builds submit --config cloudbuild.yaml --region asia-south1 \
  --substitutions=_TAG=v4
```

`.gcloudignore` uploads `.env` on purpose, because it is baked into the image. A copy of the
source, including `.env`, stays in the Cloud Build source bucket.

### 3. Point the job at the new image

Set `runner_image` to the new tag in `terraform/envs/dev/terraform.tfvars`, then:

```bash
cd terraform/envs/dev
export GOOGLE_OAUTH_ACCESS_TOKEN=$(gcloud auth print-access-token --account mr.saiful.azad@gmail.com)
terraform init        # first time only
terraform fmt -recursive && terraform validate && terraform plan -out tfplan
terraform apply tfplan  # review the plan first
```

If you only want to try a new tag once, without Terraform, run
`gcloud run jobs update tts-runner-dev --region asia-south1 --image <image:tag>`.
The next `terraform plan` will then show the difference.

### 4. Execute

Arguments are passed with `--args`, comma-separated, with no spaces:

```bash
RUN_ID=$(date -u +%Y%m%d-%H%M)-$(git rev-parse --short=7 HEAD)

# smoke test: 5 rows, batch + stream
gcloud run jobs execute tts-runner-dev --region asia-south1 --wait \
  --args=--provider,elevenlabs,--run-id,$RUN_ID,--batch,--stream,--limit,5

# full dataset, same run id for every provider
gcloud run jobs execute tts-runner-dev --region asia-south1 --wait \
  --args=--provider,elevenlabs,--run-id,$RUN_ID,--batch,--stream
gcloud run jobs execute tts-runner-dev --region asia-south1 --wait \
  --args=--provider,sarvam,--run-id,$RUN_ID,--batch,--stream
```

- The `--args` you pass replace the job's arguments for that execution only.
- If an execution fails or times out, the job timeout is 3600 s. Run the same command with the
  same `RUN_ID` to resume. Finished items are skipped and not billed again.
- Sarvam allows 30 requests per minute on the Starter plan. A full run is slow but finishes;
  A 429 is recorded as an `error` (nothing is retried).

### 5. Check results and logs

```bash
gcloud storage ls -r gs://test-ml-nasim/tts-bench/runs/$RUN_ID/

gcloud storage cat \
  gs://test-ml-nasim/tts-bench/runs/$RUN_ID/elevenlabs/eleven_v4/george/stream/manifest.jsonl \
  | head -3

gcloud run jobs executions list --job tts-runner-dev --region asia-south1 --limit 5
gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="tts-runner-dev"' \
  --limit 50 --format='value(jsonPayload.message, jsonPayload.item_id, jsonPayload.status, jsonPayload.rtf)'
```

To download a run locally:

```bash
gcloud storage cp -r gs://test-ml-nasim/tts-bench/runs/$RUN_ID ./local/audio/runs/
```

---

## Repo layout

```
config/providers.yaml          model IDs, voices, formats, prices (the only place they live)
runner/main.py                 CLI and loop: one row at a time, resume, manifest, RTF
runner/dataset.py              xlsx loader and validation (text is never modified)
runner/storage.py              output paths and the FUSE-safe manifest
runner/providers/base.py       SynthesisResult, chunk timing
runner/providers/<name>/       _common.py, batch.py, stream.py, __init__.py (create)
runner/Dockerfile              python:3.12-slim and ffmpeg; .env baked in
cloudbuild.yaml                test, build, push
terraform/envs/dev/            Cloud Run jobs only (existing bucket, repo and SA)
tests/                         pytest; HTTP mocked with respx
```

To add a provider in Claude Code, ask it to "add <vendor> as a provider". That runs the
`add-tts-provider` skill and follows `.claude/rules/providers/_contract.md`.

## How the Claude Code instructions load

| File | Loads |
|---|---|
| `CLAUDE.md` (repo root) | Always: overview, layout, guardrails |
| `.claude/rules/architecture.md`, `security.md` | Always |
| `.claude/rules/terraform.md` | When working on `terraform/**` |
| `.claude/rules/gcs-fuse.md`, `data-contract.md`, `python-runner.md` | Runner and eval code |
| `.claude/rules/providers/_contract.md` | Any provider file or `providers.yaml` |
| `.claude/rules/providers/<name>.md` | Only that provider's module and test |
| `.claude/skills/add-tts-provider/` | On demand, when adding a provider |
| `.claude/settings.json` | Permissions: plan allowed, apply/destroy denied, secret files unreadable |
