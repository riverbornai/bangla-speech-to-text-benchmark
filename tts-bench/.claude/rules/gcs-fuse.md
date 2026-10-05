---
paths:
  - "runner/**/*.py"
  - "eval/**/*.py"
  - "terraform/modules/tts_job/**"
  - "terraform/modules/eval_job/**"
---
# Working with GCS FUSE mounts

GCS FUSE behaves like a filesystem but is object storage underneath. Code must respect:

- **Write each object once, then close.** Data uploads on close. Build the whole audio bytes
  in memory, then `open(path, "wb").write(...)`. No streaming partial writes, no seek.
- **No appends.** Buffer manifest lines and write `manifest.jsonl` at the end (and every
  50 items as a checkpoint, by rewriting the whole file).
- **Rename is not atomic** and is slow — don't use tmp-file-then-rename patterns.
- **Idempotent resume:** before synthesizing, `os.path.exists(target)` → skip. A retried task
  must not re-bill provider calls for items already on disk.
- Create directories with `os.makedirs(..., exist_ok=True)`.
- Listing large directories over FUSE is slow — never `os.listdir` the audio root in a loop;
  build expected paths from the dataset instead.
- Read the xlsx once at startup (`openpyxl` / `pandas`), not per item.
