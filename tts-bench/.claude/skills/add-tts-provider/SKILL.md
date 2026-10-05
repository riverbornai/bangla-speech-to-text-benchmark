---
name: add-tts-provider
description: Add a new text-to-speech provider (e.g. Amazon Polly, xAI, Inworld, Qwen, a new open model) to the Bangla TTS benchmark — provider module, config entry, secret, Terraform job, and tests. Use whenever the user asks to add, onboard, or benchmark a new TTS model or vendor.
---

# Add a TTS provider

Follow these steps in order. Stop and ask the user if a step can't be completed.

1. **Verify Bangla support from official docs.** Find the provider's language list and
   models endpoint. Record: model IDs, whether `bn-BD`/`bn` is listed, voice IDs, max input
   chars, output formats, streaming support, rate limits, price per unit. Put the doc URLs
   in a comment in `config/providers.yaml`. If Bangla is not officially listed, mark
   `bangla_support: unofficial` — it still runs, but the report flags it.
2. **Config:** add a block to `config/providers.yaml` (copy an existing block's shape).
3. **Rule file:** If the file does not exist, create `.claude/rules/providers/<name>.md` with `paths:` frontmatter
   scoped to `runner/providers/<name>.py` and its test, covering: auth, language param,
   voice choice, output format, TTFB method, billing unit, rate limits, gotchas. 
4. **Provider module:** `runner/providers/<name>.py` implementing `TTSProvider` exactly as
   in `.claude/rules/providers/_contract.md`, using the provider's official SDK (contract rule 8).
   Register it in `runner/providers/__init__.py`.
5. **Tests:** `tests/providers/test_<name>.py` with mocked HTTP; run `pytest -q`.
6. **API key:** if it needs one, tell the user the variable name to add to `.env` (never read
   or write `.env` yourself).
7. **Terraform:** add the provider name to `tts_providers` in `terraform/envs/dev/terraform.tfvars`. Run
   `terraform fmt -recursive && terraform validate && terraform plan`. Do **not** apply.
8. **Smoke test:** offer to run `python -m runner.main --provider <name> --limit 3` locally;
   only run it if the user agrees (it costs money).
9. Summarise for the user: files changed, `.env` keys to add, plan diff summary, and any
   doc facts you couldn't verify.
