provider "google" {
  project = var.project_id
  region  = var.region
}

provider "google-beta" {
  project = var.project_id
  region  = var.region
}

# Existing resources only: APIs, bucket, Artifact Registry repo and service account are not managed here.
data "google_compute_default_service_account" "default" {
  project = var.project_id
}

locals {
  env = "dev"

  labels = {
    app   = "tts-bench"
    env   = local.env
    owner = var.owner
  }

  # The same bucket is mounted twice: read-only for the dataset, read-write for outputs.
  dataset_path = "/mnt/dataset/${var.bucket_prefix}/${var.dataset_object}"
  audio_root   = "/mnt/audio/${var.bucket_prefix}"
}

# One generic job for every API provider. Provider, run id and limit are passed per execution:
#   gcloud run jobs execute tts-runner-dev --args=--provider,sarvam,--run-id,<id>,--limit,5
module "tts_runner" {
  source = "../../modules/tts_job"

  project_id            = var.project_id
  region                = var.region
  name                  = "tts-runner-${local.env}"
  image                 = var.runner_image
  service_account_email = data.google_compute_default_service_account.default.email
  dataset_bucket        = var.bucket
  audio_bucket          = var.bucket
  dataset_path          = local.dataset_path
  audio_root            = local.audio_root
  provider_config_path  = var.provider_config_path
  deletion_protection   = false
  labels                = local.labels
}

# The old per-provider job leaves Terraform state without being deleted in GCP
# (it may still have deletion protection on). Delete it by hand when ready:
#   gcloud run jobs delete tts-elevenlabs-dev --region asia-south1
removed {
  from = module.tts_job

  lifecycle {
    destroy = false
  }
}

module "eval_job" {
  source = "../../modules/eval_job"

  project_id            = var.project_id
  region                = var.region
  name                  = "tts-eval-${local.env}"
  image                 = var.eval_image
  service_account_email = data.google_compute_default_service_account.default.email
  dataset_bucket        = var.bucket
  audio_bucket          = var.bucket
  dataset_path          = local.dataset_path
  audio_root            = local.audio_root
  provider_config_path  = var.provider_config_path
  run_id                = var.run_id
  deletion_protection   = false
  labels                = local.labels
}
