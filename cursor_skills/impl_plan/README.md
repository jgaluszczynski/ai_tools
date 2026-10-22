# Impl Plan

Cursor skill that turns a task request into a review-hardened implementation
plan before any code is written. See [SKILL.md](SKILL.md) for the phases,
plan template and prompts.

## Setup

Install the skill symlink (once):

```bash
cd impl_plan && ln -sfn "$(pwd)" ~/.cursor/skills/impl-plan
```

Invoke it explicitly with `/impl-plan <task description>`. The skill has
`disable-model-invocation: true`, so the agent loads it only when named.

Requires the [coding-model-preflight](../coding_model_preflight/README.md)
skill to be installed at `~/.cursor/skills/coding-model-preflight`; without
it the skill continues on the current model and marks the plan
`Preflight: unavailable`.

Plans are written to `~/.cursor/plans/<slug>.plan.md` unless the user names
a path. Panel model slugs live in `SKILL.md` under *Panel*; update them when
Cursor's model list changes.

## Phases

| Phase | Who | Output |
| --- | --- | --- |
| 0 Preflight | orchestrator | planning model confirmed or switch suggested |
| 1 Pre-evaluation | orchestrator + `explore` subagents | draft plan: intent, context, change areas, risks, open questions |
| 2 Review | Sonnet 5.5, GPT 5.6 Sol, Opus 5.5 in parallel | findings verified and merged into strengthening proposals |
| 3 Strengthen | orchestrator or one delegated subagent | final plan with milestones, PR-ready task names, review log |

The user is asked whenever a decision is theirs to own (architecture,
contracts, data shape, conflicting requirements, scope, trade-offs, missing
reviewer models). Routine details become recorded assumptions instead.

## Borrowed patterns

- [obra/superpowers](https://github.com/obra/superpowers) `writing-plans` and
  `brainstorming`: announce-at-start, Size the Work, Review Focus, task
  Interfaces (Consumes/Produces), the Self-Review checklist (coverage,
  consistency, "lines that decide nothing", proportion), the execution
  handoff question, "say defaults out loud".
- [alirezarezvani/claude-skills](https://github.com/alirezarezvani/claude-skills)
  `adversarial-reviewer`: severity table with required action, the 2+
  reviewers promotion rule, reviewer anti-patterns.
- [Jeffallan/claude-skills](https://github.com/Jeffallan/claude-skills)
  `architecture-designer`: ADR-style Decisions (Status / Context / Decision /
  Alternatives / Consequences) and the MUST / MUST NOT block.

## Relation to other skills

- `coding-model-preflight` picks the planning and coding models from
  benchmark data.
- `review-ensemble` reviews a code diff after implementation. `impl-plan`
  reviews the plan before it, so the review panel there is tuned for design
  and risk reading rather than diff reading.
