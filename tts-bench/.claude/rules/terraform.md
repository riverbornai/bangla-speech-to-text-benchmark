---
paths:
  - "terraform/**/*.tf"
  - "terraform/**/*.tfvars"
---
# Terraform rules

## Structure
- Root module per environment in `terraform/envs/<env>/`; reusable code in `terraform/modules/`.
- Each module has `main.tf`, `variables.tf`, `outputs.tf`, `versions.tf`. Every variable has
  `type` and `description`; no untyped variables.
- Remote state: `backend "gcs"` in `envs/<env>/backend.tf`, bucket created out-of-band
  (bootstrap), prefix `tts-bench/<env>`.
- Pin `required_version` and the `google` / `google-beta` providers with `~>` constraints.
- Do **not** manage APIs, buckets, Artifact Registry, service accounts or IAM: they already exist.
  Terraform only creates the Cloud Run jobs (`modules/tts_job`, `modules/eval_job`).
- Apply common labels via a `locals { labels = {...} }` map: `app = "tts-bench"`, `env`, `owner`.

## Cloud Run jobs with GCS FUSE
- Use `google_cloud_run_v2_job`. In `template.template`:
  - `execution_environment = "EXECUTION_ENVIRONMENT_GEN2"` (required for GCS volume mounts).
  - `volumes { name = "dataset" gcs { bucket = var.dataset_bucket  read_only = true } }`
  - `volumes { name = "audio"   gcs { bucket = var.audio_bucket    read_only = false } }`
  - `volume_mounts` at `/mnt/dataset` and `/mnt/audio` on the container.
  - `task_count`, `parallelism`, `max_retries`, and `timeout` are module variables, with defaults
    of 1, 1, 1, and `"3600s"` (one task loops over the whole dataset).
- One generic synthesis job, `tts-runner-<env>`, from `modules/tts_job`. No per-provider jobs.
- Job env vars are fixed infra paths only: `DATASET_PATH`, `AUDIO_ROOT`, `PROVIDER_CONFIG_PATH`.
  Provider, run id and limit are passed per execution with `--args`, never as env vars.
- GPU job (IndicF5): `nvidia-l4`, set node selector + limits per current Cloud Run GPU docs;
  check GPU availability for the chosen region before writing the resource.

## Identity
- Jobs run as the existing default compute SA, looked up with
  `data "google_compute_default_service_account"` (don't hardcode the project number).
- No Secret Manager: API keys ship in the image's `.env`.

## Hygiene
- `terraform fmt -recursive` and `terraform validate` must pass before you say you're done.
- Never write secret values, API keys, or project numbers into `.tf` / `.tfvars`.
- Never run `apply` / `destroy`. Show `plan` output and stop.
- Job names: `tts-<component>-<env>`. Bucket/repo names come from `terraform.tfvars`.
