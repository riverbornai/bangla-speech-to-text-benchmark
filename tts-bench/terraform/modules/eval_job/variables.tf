variable "project_id" {
  type        = string
  description = "GCP project ID."
}

variable "region" {
  type        = string
  description = "Cloud Run region."
}

variable "name" {
  type        = string
  description = "Job name, e.g. tts-eval-dev."
}

variable "image" {
  type        = string
  description = "Container image for the eval job."
}

variable "service_account_email" {
  type        = string
  description = "Eval service account."
}

variable "dataset_bucket" {
  type        = string
  description = "Dataset bucket, mounted read-only at /mnt/dataset."
}

variable "audio_bucket" {
  type        = string
  description = "Audio bucket, mounted at /mnt/audio."
}

variable "dataset_path" {
  type        = string
  description = "Path of the dataset workbook inside the container."
}

variable "provider_config_path" {
  type        = string
  description = "Path of providers.yaml inside the container."
}

variable "run_id" {
  type        = string
  description = "Default RUN_ID; override per execution."
}

variable "extra_env" {
  type        = map(string)
  description = "Additional plain env vars. Cannot override the standard ones."
  default     = {}
}

variable "cpu" {
  type        = string
  description = "CPU limit per task (UTMOS + ASR are CPU-heavy)."
  default     = "4"
}

variable "memory" {
  type        = string
  description = "Memory limit per task."
  default     = "8Gi"
}

variable "task_count" {
  type        = number
  description = "Number of tasks per execution."
  default     = 1
}

variable "parallelism" {
  type        = number
  description = "Max concurrent tasks."
  default     = 1
}

variable "max_retries" {
  type        = number
  description = "Retries per failed task."
  default     = 1
}

variable "timeout" {
  type        = string
  description = "Per-task timeout."
  default     = "3600s"
}

variable "deletion_protection" {
  type        = bool
  description = "Block Terraform from deleting the job."
  default     = true
}

variable "labels" {
  type        = map(string)
  description = "Labels applied to the job and its executions."
}

variable "audio_root" {
  type        = string
  description = "Output root inside the container (under the /mnt/audio mount)."
  default     = "/mnt/audio"
}
