---
name: coding-model-preflight
description: >-
  Recommend the Cursor model with the strongest current public coding benchmark
  signal among configured slugs. Use before substantial coding work (multi-file
  implementation, refactor, complex debugging, code review, test generation) or
  when the user asks which model to use. Do not use for trivial edits or when
  the user already selected a model.
---

# Coding Model Preflight

Before selecting a model for substantial coding work, run from this skill
directory:

```bash
python3 scripts/preflight.py select --json
```

## Use the result

1. Read `selected_model` from the JSON output.
2. Cross-check it against the models available in this session. If it is not
   available, use the first available entry from `alternatives`.
3. Report one line: model, confidence, snapshot age, primary source.
4. If the current chat model differs, tell the user to switch before starting.
5. Use the slug for the `model` parameter when launching subagents.
6. If `confidence` is `low` or `cache.used_stale_data` is true, say so.
7. Never claim the selected model is guaranteed best for this repository.

If the user explicitly selected a model, do not override them. Offer the
preflight result only on request.

## Maintenance

If important slugs appear in `exclusions` or `status --unmapped` shows a new
top external model, suggest updating [config.json](config.json). See
[README.md](README.md) for mapping instructions.
