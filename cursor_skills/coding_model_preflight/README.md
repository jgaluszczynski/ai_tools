# Coding Model Preflight

Recommend Cursor model slugs from public benchmark data, split by task.

## Tasks and roles

`select --json` returns `tasks.coding` and `tasks.planning`. Coding ranks on
Artificial Analysis `coding_index` (equal scores break on aistupidlevel).
Planning ranks on Artificial Analysis `intelligence_index`. Each task lists up
to three picks:

| Role | Rule |
| --- | --- |
| `strong` | Highest task score. |
| `similarly_strong` | Next score, within `near_tie_margin` of strong. Labeled `next_best` when the gap is larger. |
| `cost_efficient` | Cheapest completion price among the remaining models within `cost_quality_margin` of strong and cheaper than strong. Omitted when none qualify. |

`selected_model` stays the coding `strong` slug.

When OpenRouter is unavailable, planning reuses the aistupidlevel order with
`confidence: low` and a `note`, because that score is coding-heavy. A slug
with only an aistupidlevel score is excluded from planning while OpenRouter
data exists.

Unused signals: Artificial Analysis `agentic_index` and aistupidlevel's
`codeQuality` axis. Neither answers the coding or planning question above, and
neither predicts pull-request review volume.

## Setup

1. Optional but recommended: create a free [OpenRouter](https://openrouter.ai/)
   API key. Either place it in `.env` in this directory (loaded automatically)
   or export it in your shell:

   ```bash
   echo 'OPENROUTER_API_KEY="sk-or-..."' > .env
   # or: export OPENROUTER_API_KEY="sk-or-..."
   ```

   Without a key, the tool falls back to keyless
   [aistupidlevel.info](https://aistupidlevel.info) scores only.

2. Install the skill symlink (once):

   ```bash
   ln -sf "$(pwd)" ~/.cursor/skills/coding-model-preflight
   ```

## Usage

From this directory:

```bash
python3 scripts/preflight.py select --json
python3 scripts/preflight.py refresh
python3 scripts/preflight.py status --unmapped
```

Cache location: `~/.cache/coding-model-preflight/snapshot.json` (or
`$XDG_CACHE_HOME/coding-model-preflight/snapshot.json`).

## Maintaining model mappings

Cursor slugs in `config.json` must be mapped manually to external benchmark
identifiers:

- `openrouter_ids`: OpenRouter `model_permaslug` values from
  `status --unmapped` / the benchmarks API (include date suffixes, e.g.
  `anthropic/claude-opus-5-20260723`).
- `aistupidlevel_names`: model names from aistupidlevel dashboard
  (`claude-opus-4-8`, `gpt-5.6-sol`, etc.).

Run `python3 scripts/preflight.py status --unmapped` after a refresh to see top
external models that are not yet mapped. Add IDs to the matching Cursor slug.

Cursor-only models (e.g. `composer-2.5-fast`, `cursor-grok-4.6-xhigh-fast`)
typically have no public score and will appear in `exclusions`. That is expected.

## Deferred

LiveCodeBench, SWE-bench, capability filters, sessionStart hook, scheduled
source-schema CI.
