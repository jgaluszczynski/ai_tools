# Review Ensemble

Cursor skill that reviews a diff with four models plus Bugbot and Security
Review in parallel, normalizes and deduplicates their output with a cheap
model, validates every candidate with an independent model, applies the
merge rules with a script, and has a cheap merger write one deduplicated
findings table with numbered fix proposals and a merge verdict. See
[SKILL.md](SKILL.md) for the panel and the run steps, [prompts/](prompts/)
for the reviewer, normalizer, validator, and merger prompts, and
[scripts/merge.py](scripts/merge.py) for the merge rules.

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

Sonnet 5.5, GPT 5.6 Sol, Opus 5.5, and Fable were requested by name. The
Fable seat resolves to the highest available version at run time
(`claude-fable-5-3-thinking-high`, else `claude-fable-5-1-thinking-high`)
and is the only seat with a fallback; every other seat is skipped when its
slug is unavailable.

Earlier versions of the panel used Grok 4.7, then Muse Spark 1.3 with
Gemini 4 Argon as fallback, and Codex 5.3. Those seats were replaced by
Opus 5.5 and Fable, which trade model-family diversity for the two
strongest Anthropic reviewers.

Bugbot and Security Review run alongside the panel because they use their
own harnesses and prompts, which adds coverage the model panel does not
duplicate. Their rows are normalized into the same schema and count toward
agreement in the merge.

Greptile's [model inversion](https://www.greptile.com/blog/model-inversion)
result (1,000 PRs: a reviewer model different from the authoring model finds
roughly 10% more P0/P1 bugs, because a model tends to miss the bug classes it
introduces) is context for future seat decisions. It argues for keeping at
least one non-Anthropic seat when most code in a repository is written with
Claude; it did not change the panel.

## Why a validator

Every production reviewer studied has a verification stage between
generation and output: Copilot code review runs an `Autovalidate` job after
its agent stage ([example Actions run](https://github.com/keithah/multi-provider-code-review/actions/runs/21332184745)),
Claude Code Review has a Find, Verify, Rank, Post pipeline with voting
verifiers ([docs](https://code.claude.com/docs/en/code-review)), Bugbot's
launch pipeline ended in a validator model
([Building a better Bugbot](https://cursor.com/blog/building-bugbot)), and
Uber's uReview chains generation, filtering, validation, and deduplication
([blog](https://www.uber.com/us/en/blog/ureview/)).

Two details shaped the validator prompt. Sourcery found that a generic "is
this useful?" judge did nothing (43% vs 42% useful) while decomposed yes/no
criteria (valid to the code, actionable, specific, valuable to the author)
took usefulness from the low 40s to about 60%
([post](https://www.sourcery.ai/blog/improving-llm-responses)); Greptile
found a 1-10 severity judge "nearly random"
([post](https://www.greptile.com/blog/make-llms-shut-up)). So the validator
returns booleans with quoted evidence, not a score. Trail of Bits notes that
a model "favors findings it produced when asked to check them"
([spec-to-code-compliance](https://github.com/trailofbits/skills/blob/main/plugins/spec-to-code-compliance/skills/spec-to-code-compliance/SKILL.md)),
so the validator is a non-Anthropic model and never sees reviewer names or
agreement counts.

With a validator in place, the merge keeps single-reviewer `medium` and
`high` findings that survive it instead of dropping them. ReviewBench shows
precision in a narrow band for every product and rank decided by recall, and
GitHub's ensemble gained its +13.6% recall by keeping findings that one run
surfaced and another confirmed.

The validator also corrects a finding instead of dropping it when the code
confirms the defect but disproves a statement in its text (the impact, a
name, a location). SpotOn's `ai-pr-review` verifier does the same, on the
reasoning that a posted finding should not carry a claim the code refutes.
Normalization and duplicate matching run on a cheap model (Haiku, else
Gemini Flash, else Composer) in their own subagent, and the merge itself
is a script, so no model spends tokens matching duplicates or applying
rules. Each subagent prompt also carries a tool-call budget; the `Task`
tool has no turn cap, so the budgets are advisory and any `budget reached`
is reported in Coverage.

## Why files and a script

An earlier version of this skill had the parent chat carry every byte
between stages: it pasted the repo instruction files into four reviewer
prompts and the validator prompt, pasted all six raw reviewer outputs into
the normalizer prompt, pasted the candidate list into the validator
prompt, applied the merge rules in its head, and wrote the whole report.
Each of those is parent output, and output tokens cost roughly five times
input tokens; the parent is also usually the most expensive model in the
session. That added up to an estimated 20-30k output tokens per run on
top of the reviewers' own work.

Now every stage reads from and writes to a run directory. The parent
writes the inputs with shell redirects (zero tokens), launches each
subagent with a five-line prompt that points at a template in
`prompts/`, runs `scripts/merge.py` to apply the merge rules (zero
tokens, deterministic, covered by `tests/test_merge.py` through
`make test`), and prints the script's summary plus the report path. The
only reviewer output the parent re-emits is the two small Bugbot and
Security Review tables, because those subagents cannot read files.
Expected parent output per run is now 2-3k tokens.

SpotOn's `ai-pr-review` CI pipeline moves data the same way (artifacts and
files, JS for the deterministic steps, a model only where judgment is
needed), which is where the pattern was borrowed from.

### Merger seat

The merger writes Fixes against a table it may not change, so it needs
synthesis and precise edit instructions, not the panel's strongest
reviewer. Picked from the coding-model-preflight snapshot
(OpenRouter / Artificial Analysis, captured 2026-10-23; coding index /
intelligence index / output price per million tokens), restricted to slugs
available in Cursor:

| Order | Slug | Coding | Intelligence | Output $/M | Note |
| --- | --- | --- | --- | --- | --- |
| 1 | `muse-spark-1.3-high` | 75.8 | 48.1 | 4.25 | Second-highest intelligence index after Fable 5.1 (53.4), within 6 coding points of it, one sixth of its $25/M |
| 2 | `gemini-3.8-flash-high` | 76.3 | 40.9 | 4.13 | Slightly better coding, weaker synthesis |
| 3 | `glm-5p3-high` | 74.8 | 44.8 | 3.08 | Cheapest in range |

Not chosen: `gpt-5.6-sol-medium` ($40/M, pricier than Fable),
`kimi-k3-max` ($10.5/M, lower intelligence than Muse), and the Sonnet,
Opus, and Haiku 5.5 slugs, which have no public price or score in the
snapshot. Revisit when the snapshot changes; `coding_model_preflight`
does not yet map these slugs, so the order is fixed here rather than
computed.

## Why Copilot-style inputs

GitHub documents what its review agent reads and does, and most of it is
reproducible with shell tools:

- Whole changed files rather than hunks
  ([changelog 2025-04-23](https://github.blog/changelog/2025-04-23-github-copilot-code-review-now-supports-c-c-kotlin-and-swift/)).
- Agentic exploration that starts from the diff, narrows with `grep` and
  `glob`, and reads exact ranges
  ([blog](https://github.blog/ai-and-ml/github-copilot/better-tools-made-copilot-code-review-worse-heres-how-we-actually-improved-it/)).
- PR title and body plus linked issues as intent, and repository
  instruction files: `.github/copilot-instructions.md`,
  `.github/instructions/*.instructions.md` with `applyTo`, and `AGENTS.md`
  ([docs](https://docs.github.com/en/copilot/concepts/agent-capabilities/agent-powered-workflows-and-operations/code-review)).
- Lockfiles, manifests, logs, and SVGs excluded from review (same docs).
- Build, test, and linter output folded in, which "surfaced more high
  severity findings and fewer nits"
  ([changelog 2026-09-11](https://github.blog/changelog/2026-09-11-auto-resolution-and-analysis-updates-in-copilot-code-review/)).
- Severity on every comment, about five comments per review, and silence
  when nothing clears the bar
  ([60M reviews](https://github.blog/ai-and-ml/github-copilot/60-million-copilot-code-reviews-and-counting/)).
- Suggested-change blocks, the strongest predictor that a comment is acted
  on (odds ratio 1.62 across 54,791 agent comments,
  [arXiv 2607.21997](https://arxiv.org/html/2607.21997v2)).

The reviewer prompt's precision guards come from the same corpus: the
"provably affected" and "would the author fix it" tests from Codex's
[review rubric](https://github.com/openai/codex/blob/main/codex-rs/prompts/templates/review/rubric.md),
the copy-paste genericity test and "Do not guess. Verify." from the
ReviewBench [judge prompt](https://github.com/review-bench/ReviewBench/blob/main/scripts/classifier/prompts.ts),
and the `declined` list from
[obra/superpowers](https://github.com/obra/superpowers/blob/main/skills/requesting-code-review/code-reviewer.md).

Not adopted: free-form reviewer debate (lowest F1 in
[SWR-Bench](https://arxiv.org/abs/2509.01494)), numeric confidence as the
filter, and feedback-driven suppression of comment clusters (the largest
measured production gain, but it needs stored feedback across runs).

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
