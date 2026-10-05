# Security & secrets (always loaded)

- API keys live in `.env` (gitignored, never committed), copied into the runner image at build
  time and loaded with python-dotenv. Anyone who can pull the image can read the keys: keep the
  Artifact Registry repo private, and rebuild + rotate the key if it leaks.
- Never put keys in code, `.tf`, `.tfvars`, or Terraform state.
- Jobs use the project's default compute service account (user's choice).
- No service-account JSON keys. Local dev uses `gcloud auth application-default login`.
- Never log request headers, API keys, or full provider responses. Log status code,
  latency, request id, and byte count only.
- Buckets: uniform bucket-level access ON, public access prevention `enforced`.
- Dataset text is not secret, but reference voice audio for cloning is: only the IndicF5
  service account may read `reference_audio/`.
