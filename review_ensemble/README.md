# Review Ensemble

Cursor skill that reviews a diff with four models plus Bugbot and Security
Review in parallel and merges their findings into one deduplicated findings
table with numbered fix proposals. See [SKILL.md](SKILL.md) for the panel,
reviewer prompts, and merge rules.

## Setup

Install the skill symlink (once):

```bash
ln -sfn "$(pwd)" ~/.cursor/skills/review-ensemble
```

Invoke it explicitly with `/review-ensemble`. The skill has
`disable-model-invocation: true`, so the agent loads it only when named.

## Why a panel

GitHub's [ReviewBench](https://review-bench.ai/) leaderboard (2026-10 capture)
shows every reviewer with precision in a narrow 84-90% band while grounded
recall ranges from 26% down to under 10%. The gap between reviewers is what
they miss. GitHub reported that a multi-model ensemble raised recall 13.6%
and addressed rate 8% in production while comment volume rose 61%. The merge
step in this skill keeps the recall and removes the volume: one instruction
per issue, duplicates and single-reviewer nits dropped.

## Panel choice

Sonnet 5.5, GPT 5.6 Sol, and Codex 5.3 were requested by name. The fourth
seat was Grok 4.7, which was the slowest of the group. It was replaced with
Muse Spark 1.3 using the preflight cache (Artificial Analysis via
OpenRouter, 2026-10-13) and the Artificial Analysis speed board
(2026-10-14):

| Slug | Intelligence | Coding | Output $/M | Output speed |
| --- | --- | --- | --- | --- |
| `grok-4.7-high-fast` | 46.4 | - | 6.60 | 86 tok/s |
| `muse-spark-1.3-high` | 48.1 | 75.8 | 4.25 | 239 tok/s |
| `gemini-4-argon-medium` | 52.6 | - | 5.00 | not published |
| `claude-haiku-5-5-thinking-high` | 43.4 | - | 0.55 | 175 tok/s |

Muse Spark 1.3 scores higher than Grok 4.7, costs less, is about 2.8x
faster, and adds a fourth model family. Gemini 4 Argon scores higher still
but has no published speed, so it is the documented fallback for that seat.
Haiku is cheapest but scores below Grok and shares a family with Sonnet.

Bugbot and Security Review run alongside the panel because they use their
own harnesses and prompts, which adds coverage the model panel does not
duplicate. Their rows are normalized into the same schema and count toward
agreement in the merge.

## Why ReviewBench scores stay out of coding-model-preflight

[coding_model_preflight](../coding_model_preflight/README.md) maps Cursor
slugs to per-model benchmark indices. ReviewBench scores complete review
products (harness, prompts, tools, and model together), so a row such as
"Cursor" or "Codex GPT-5.6 Sol Max" describes one product configuration and
has no clean mapping to a Cursor slug. The leaderboard has no rows for most
slugs in the panel, the site renders it client-side, and the initial entries
were run by the ReviewBench team on vendor products that may have changed
since. A `tasks.review` entry in the preflight would be guesswork, so it is
deliberately absent.
