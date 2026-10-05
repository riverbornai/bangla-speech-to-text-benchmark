variable "project_id" {
  type        = string
  description = "GCP project ID (not the project number)."
}

variable "region" {
  type        = string
  description = "Cloud Run region."
}

variable "owner" {
  type        = string
  description = "Value of the `owner` label (lowercase letters, digits, - and _)."
}

variable "bucket" {
  type        = string
  description = "Existing GCS bucket holding the dataset and generated audio."
}

variable "bucket_prefix" {
  type        = string
  description = "Folder inside the bucket for everything this benchmark reads and writes."
  default     = "tts-bench"
}

variable "image_repository" {
  type        = string
  description = "Existing Docker repo, e.g. asia-south1-docker.pkg.dev/<project>/cloud-run-source-deploy."
}

variable "runner_image" {
  type        = string
  description = "Runner image; contains .env with the provider API keys, so keep the registry private."
}

variable "eval_image" {
  type        = string
  description = "Image for the eval job."
}

variable "dataset_object" {
  type        = string
  description = "Dataset workbook path under <bucket>/<bucket_prefix>/."
  default     = "dataset/bangla_tts_benchmark_dataset_v0.1.xlsx"
}

variable "provider_config_path" {
  type        = string
  description = "Path of providers.yaml baked into the images."
  default     = "/app/config/providers.yaml"
}

variable "run_id" {
  type        = string
  description = "Placeholder RUN_ID on the job definition; set the real one per execution with --update-env-vars."
  default     = "unset"
}
