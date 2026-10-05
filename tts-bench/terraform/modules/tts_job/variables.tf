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
  description = "Job name, e.g. tts-runner-dev."
}

variable "image" {
  type        = string
  description = "Runner image (contains .env with the provider API keys)."
}

variable "service_account_email" {
  type        = string
  description = "Dedicated service account the job runs as."
}

variable "dataset_bucket" {
  type        = string
  description = "Dataset bucket, mounted read-only at /mnt/dataset."
}

variable "audio_bucket" {
  type        = string
  description = "Audio bucket, mounted read-write at /mnt/audio."
}

variable "dataset_path" {
  type        = string
  description = "Path of the dataset workbook inside the container."
}

variable "provider_config_path" {
  type        = string
  description = "Path of providers.yaml inside the container."
}

variable "cpu" {
  type        = string
  description = "CPU limit."
  default     = "1"
}

variable "memory" {
  type        = string
  description = "Memory limit."
  default     = "1Gi"
}

variable "task_count" {
  type        = number
  description = "Tasks per execution. 1 = the whole dataset in a single loop."
  default     = 1
}

variable "parallelism" {
  type        = number
  description = "Max concurrent tasks."
  default     = 1
}

variable "max_retries" {
  type        = number
  description = "Retries of a failed task; already-synthesized rows are skipped, so retries don't re-bill."
  default     = 1
}

variable "timeout" {
  type        = string
  description = "Task timeout."
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
