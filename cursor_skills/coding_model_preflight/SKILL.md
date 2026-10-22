---
name: coding-model-preflight
description: >-
  Recommend Cursor models from current public benchmark signal, split by task:
  coding (implementation, refactor, debugging, tests, review) and planning
  (analysis and design before code). Each task returns a strong pick, a close
  second, and a cheaper pick that is still near the top. Use before substantial
  coding or planning work, or when the user asks which model to use. Do not use
  for trivial edits or when the user already selected a model.
---

# Coding Model Preflight

Before selecting a model for substantial coding or planning work, run from
this skill directory:

```bash
python3 scripts/preflight.py select --json
```

## Use the result

1. Pick the task:
   - `tasks.coding` for implementation, refactor, debugging, test generation,
     and code review.
   - `tasks.planning` for analysis, architecture, and plan writing before
     code. Plan-then-implement work uses planning for the plan and coding for
     the edits.
2. Each task lists up to three `picks` by `role`:
   - `strong`: highest task score.
   - `similarly_strong`: next score, inside the near-tie margin. When the
     gap is larger the role is `next_best` instead.
   - `cost_efficient`: cheapest output price among the remaining models
     (after `strong` and the second pick) within `cost_quality_margin`
     points of strong and cheaper than strong. Absent when nobody qualifies.
3. Cross-check slugs against the models available in this session. Skip any
   pick that is unavailable and move to the next role.
4. Report one line per pick plus task confidence, snapshot age, and primary
   source. `selected_model` is the coding `strong` slug.
5. If the current chat model differs from the `strong` pick for the work
   about to start, tell the user which slug to switch to.
6. Use the chosen slug for the `model` parameter when launching subagents.
7. If a task's `confidence` is `low`, `cache.used_stale_data` is true, or the
   task carries a `note`, say so.
8. Never claim a pick is guaranteed best for this repository.

## Review churn

These scores do not predict pull-request comment volume. If the `strong`
coding model has been producing repeated review rounds on recent PRs, switch
implementation to the `similarly_strong` (or `next_best`) pick and keep
`strong` for planning. Base that on observed review rounds, and avoid a
standing ban on any one model.

If the user explicitly selected a model, do not override them. Offer the
preflight result only on request.

## Maintenance

If important slugs appear in `exclusions` or `status --unmapped` shows a new
top external model, suggest updating [config.json](config.json). See
[README.md](README.md) for mapping instructions.
