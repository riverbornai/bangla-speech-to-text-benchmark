output "dataset_gcs_path" {
  description = "Upload the dataset workbook here."
  value       = "gs://${var.bucket}/${var.bucket_prefix}/${var.dataset_object}"
}

output "runs_gcs_path" {
  description = "Generated audio and manifests land under this prefix."
  value       = "gs://${var.bucket}/${var.bucket_prefix}/runs/"
}

output "runner_image_name" {
  description = "Tag to build and push the runner image as."
  value       = "${var.image_repository}/tts-runner"
}

output "runner_job" {
  description = "Generic synthesis job; pick the provider with --args=--provider,<name>."
  value       = module.tts_runner.name
}

output "eval_job" {
  description = "Eval Cloud Run job name."
  value       = module.eval_job.name
}

output "service_account" {
  description = "Service account both jobs run as (existing default compute SA)."
  value       = data.google_compute_default_service_account.default.email
}
