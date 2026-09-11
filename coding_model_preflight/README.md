# Coding Model Preflight

Recommend a Cursor model slug from public coding benchmark data.

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

LiveCodeBench, SWE-bench, task profiles, capability filters, sessionStart hook,
scheduled source-schema CI.
