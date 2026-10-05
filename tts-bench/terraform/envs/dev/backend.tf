# State bucket is created out-of-band. Supply it at init:
#   terraform init -backend-config="bucket=<state-bucket>"
terraform {
  backend "gcs" {
    prefix = "tts-bench/dev"
  }
}
