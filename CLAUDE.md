# Bangla TTS Benchmark — Project Memory

## What this repo does
Benchmarks text-to-speech providers on Bangla (bn-BD). A dataset workbook on GCS
drives synthesis jobs on Cloud Run; every generated clip and its metadata land in a
GCS bucket via GCS FUSE volume mounts. A separate eval job scores the audio.

## Repo layout (create exactly this; do not invent new top-level dirs)
```
terraform/                 # all infra (see .claude/rules/terraform.md)
  envs/dev/                # root module per env: backend.tf, main.tf, variables.tf, terraform.tfvars
  modules/
    tts_job/               # Cloud Run v2 job module, used once as the generic tts-runner-<env> job
    eval_job/
runner/                    # synthesis container (Python 3.12)
  main.py                  # entrypoint: loops over every dataset row, calls provider
  dataset.py               # xlsx loader + validation (see data-contract rule)
  storage.py               # path layout + manifest writing on the FUSE mount
  providers/
    base.py                # TTSProvider protocol + SynthesisResult dataclass
    <name>/                # one package per provider: _common.py, batch.py, stream.py, __init__.py
                           # (elevenlabs/, sarvam/; later gemini/, azure/, cartesia/, openai_tts/, indicf5/)
  Dockerfile
eval/                      # ASR round-trip CER, UTMOS, report builder
config/providers.yaml      # model IDs, voices, pricing — the ONLY place these live
```

## Core architecture (non-negotiable)
- Compute: **one generic Cloud Run v2 Job** (`tts-runner-<env>`) for all API providers, **one model per
  provider**, a single task that loops over every dataset row sequentially (no sharding, no concurrency).
  Per-run choices are CLI args passed at execution, never job env vars:
  `gcloud run jobs execute tts-runner-dev --args=--provider,<name>,--run-id,<id>[,--batch][,--stream][,--limit,5]`
  (no mode flag = batch; both flags run batch then stream).
- Uses **existing** resources only (Terraform creates just the Cloud Run jobs): bucket `test-ml-nasim`
  (everything under `tts-bench/`), Artifact Registry `asia-south1/cloud-run-source-deploy`, and the
  default compute service account. Do not enable APIs or create buckets, repos, SAs or IAM bindings.
- The bucket is mounted twice: **read-only** at `/mnt/dataset`, **read-write** at `/mnt/audio`.
- API keys live in `.env` (gitignored), which is copied into the runner image. No Secret Manager.
  Never commit `.env` or put keys in code / tfvars; keep the Artifact Registry repo private.
- Google APIs (Gemini-TTS) authenticate with the job's service account (ADC). No JSON keys anywhere.
- Same image for all API providers; provider selected by the `--provider` CLI arg.
  IndicF5 (self-hosted, GPU) gets its own image and job.

## Commands
- Terraform: `cd terraform/envs/dev && terraform fmt -recursive && terraform validate && terraform plan`
- Runner locally: `python -m runner.main --provider gemini --limit 5 --dataset ./local/dataset.xlsx --out ./local/audio`
- Tests: `pytest -q`
- Lint: `ruff check . && ruff format --check .`

## Working rules for Claude
- Run `terraform plan` freely; **never run `terraform apply` or `destroy`** — print the plan and stop.
- Never call paid TTS APIs except with `--limit 5` or less unless the user says otherwise.
- Before adding or changing a provider, read `.claude/rules/providers/_contract.md`
  and the provider's own rule file. Use the `add-tts-provider` skill for new providers.
- Model IDs, voice names and API versions change: verify against the provider's
  list-models / list-voices endpoint, then record them in `config/providers.yaml`.
  Never hardcode them in Python.
- If something in these rules conflicts with official provider docs, follow the docs
  and tell the user which rule is stale.

## Definitions
- `run_id`: `YYYYMMDD-HHMM-<shortsha>` set once per benchmark run, passed to every job.
- `item_id`: the `id` column of the Dataset sheet (e.g. `BN-NUM-010`).
