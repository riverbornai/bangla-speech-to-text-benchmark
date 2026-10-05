project_id = "connekt-studio"
region     = "asia-south1" # Mumbai, same as the image repo; bucket is in asia-southeast1
owner      = "saiful-azad"

bucket           = "test-ml-nasim"
image_repository = "asia-south1-docker.pkg.dev/connekt-studio/cloud-run-source-deploy"

# Google's sample job image lets infra apply before our image exists.
# Switch to "<image_repository>/tts-runner:<tag>" once pushed.
runner_image = "asia-south1-docker.pkg.dev/connekt-studio/cloud-run-source-deploy/tts-runner:v3"
eval_image   = "us-docker.pkg.dev/cloudrun/container/job:latest"
