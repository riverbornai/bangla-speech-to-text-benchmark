# Bangla TTS Benchmark — Claude Code scaffold

This repo contains only the **Claude Code instructions** (memory + rules + skill + config).
Open it in Claude Code and ask it to build the code, e.g.:

1. "Build the Terraform for dev following the rules" → it writes `terraform/` and runs `plan`.
2. "Implement the runner and the Gemini and Azure providers" → `runner/`, tests.
3. "Implement the eval job" → `eval/`.
4. "Add Amazon Polly as a provider" → triggers the `add-tts-provider` skill.

## How the instructions load
| File | Loads |
|---|---|
| `CLAUDE.md` | Always — project overview, layout, guardrails |
| `.claude/rules/architecture.md`, `security.md` | Always (no `paths:` frontmatter) |
| `.claude/rules/terraform.md` | Only when working on `terraform/**` |
| `.claude/rules/gcs-fuse.md`, `data-contract.md`, `python-runner.md` | Runner / eval code |
| `.claude/rules/evaluation.md` | `eval/**` |
| `.claude/rules/providers/_contract.md` | Any provider file or providers.yaml |
| `.claude/rules/providers/<name>.md` | Only that provider's module + test |
| `.claude/skills/add-tts-provider/` | On demand when adding a provider |
| `.claude/settings.json` | Permissions: plan allowed, apply/destroy denied, secret files unreadable |

Run `/memory` inside Claude Code to confirm which rules are loaded for the file you're editing.

## Manual steps (never done by Claude)
1. Create the Terraform state bucket.
2. `terraform apply` after reviewing the plan.
3. Put API keys in `tts-bench/.env` (e.g. `ELEVENLABS_API_KEY=...`) before `docker build`.
4. Upload the dataset: `gcloud storage cp bangla_tts_benchmark_dataset_v0.1.xlsx gs://<project>-tts-dataset/dataset/`
5. Fill every `VERIFY` in `config/providers.yaml`.
