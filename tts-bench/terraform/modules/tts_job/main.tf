resource "google_cloud_run_v2_job" "this" {
  project             = var.project_id
  location            = var.region
  name                = var.name
  labels              = var.labels
  deletion_protection = var.deletion_protection

  template {
    task_count  = var.task_count
    parallelism = var.parallelism
    labels      = var.labels

    template {
      service_account       = var.service_account_email
      execution_environment = "EXECUTION_ENVIRONMENT_GEN2" # required for GCS volume mounts
      max_retries           = var.max_retries
      timeout               = var.timeout

      containers {
        image = var.image

        resources {
          limits = {
            cpu    = var.cpu
            memory = var.memory
          }
        }

        dynamic "env" {
          for_each = {
            DATASET_PATH         = var.dataset_path
            AUDIO_ROOT           = var.audio_root
            PROVIDER_CONFIG_PATH = var.provider_config_path
          }
          content {
            name  = env.key
            value = env.value
          }
        }

        volume_mounts {
          name       = "dataset"
          mount_path = "/mnt/dataset"
        }

        volume_mounts {
          name       = "audio"
          mount_path = "/mnt/audio"
        }
      }

      volumes {
        name = "dataset"
        gcs {
          bucket    = var.dataset_bucket
          read_only = true
        }
      }

      volumes {
        name = "audio"
        gcs {
          bucket    = var.audio_bucket
          read_only = false
        }
      }
    }
  }
}
