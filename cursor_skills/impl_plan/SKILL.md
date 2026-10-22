---
name: impl-plan
description: >-
  Produces a review-hardened implementation plan before any code is written:
  confirms the planning model with coding-model-preflight, explores the code
  and decomposes the task into change areas, coding assumptions, risks and
  decisions from dev, QA and PM/PO perspectives, has a multi-model panel
  review the plan against the code, then outputs the strengthened plan with
  milestones, PR-ready task names and an execution handoff. Use when the user
  asks to plan a task, feature, refactor or migration, wants a plan
  challenged before coding, or names this skill.
disable-model-invocation: true
---

# Impl Plan

Four phases, each ending in a gate. The output is a plan file, not code.

**Announce at start:** "I'm using the impl-plan skill; the output is a
reviewed plan, not code."

## Must / must not

MUST: keep the subject request's wording as the intent; write every default
you take into the plan and say it to the user (a default they never heard is
one they could not reject); verify every reviewer finding against the code
before acting on it; record every finding's fate (applied, rejected, noted,
dismissed); stop at the handoff.

MUST NOT: edit source files, start implementation or open pull requests;
write code or function bodies into the plan; change a decision with Status
`decided (user)` without asking again; drop a finding silently; over-specify
for hypothetical scale or needs the request does not name.

## Terminology and question lifecycle

Reviewers return **findings**; the orchestrator turns accepted findings into
**proposals** (edits to the plan). **Assumptions** are routine defaults the
panel may challenge. **Decisions** are ADR-style records for choices that
matter (architecture, contracts, data shape, migration, trade-offs, scope).

**Open questions** holds only questions not yet asked. At every gate, each
answered question becomes a Decision with Status `decided (user)`; a
question answered "you decide" or left unanswered becomes a Decision with
Status `pending` whose Decision field holds the default taken. Nothing stays
in Open questions after a gate. "Decisions pending" means records with
Status `pending`.

## Ask-the-user rule

Stop and ask (with `AskQuestion` when available, otherwise inline) whenever a
step produces a decision the user must own:

- architecture or public-contract choice, data model or migration shape
- conflicting or mutually exclusive requirements
- scope that can be read two ways leading to materially different work
- a security, backward-compatibility or performance trade-off
- a task too large for one plan (see Phase 1 step 5)

Batch all pending questions into one call per gate, then apply the question
lifecycle to every answer. Never block on a question that has a safe
default. Routine details are not questions: pick a default and record it
under **Assumptions**.

## Phase 0 - Model preflight and panel check

Run from `~/.cursor/skills/coding-model-preflight`:

```bash
python3 scripts/preflight.py select --json
```

1. Take `tasks.planning.picks` in order `strong`, `similarly_strong` or
   `next_best`, `cost_efficient`; the first slug available in this session
   (the session's subagent model list) is the planning model, used for the
   chat and for Phase 3 delegation. Note which role was used. If the script
   is missing, exits non-zero, prints non-JSON, or no pick is available,
   say so in one line, continue on the current chat model, and write
   `Preflight: unavailable` in the plan header.
2. Resolve the Phase 2 panel against the same model list. For each missing
   slug, note the closest available model of the same family.
3. One gate, one question batch. State the planning model. If the chat
   model's slug cannot be confirmed or differs from it, ask whether to
   continue on the current model or stop so the user can switch (echo the
   task text so it can be pasted back); skip this only when the user named a
   model in the `/impl-plan` invocation. If a panel slug is missing, ask
   whether to run without that seat or seat the named same-family
   alternative. Record the answers; do not ask again this run.
4. Report one line: planning model and role, task `confidence`,
   `cache.age_hours`, `cache.used_stale_data`, any `note`, seated panel.
   Never claim the pick is guaranteed best for this repository.

## Phase 1 - Pre-evaluation and decomposition (orchestrator)

Understand the request and the code well enough to name every change area,
state how it would be coded as challengeable assumptions, and name its
risks. Think as a team would: a developer (where does this touch, what
breaks), a QA engineer (how is it verified, what is hard to test, what
regresses), and a PM/PO (user-visible outcome, what is in and out of scope,
what is ambiguous).

0. **Size the work.** Say the size in plain words; the user can override.
   A quick, clear task: the request itself is the plan; say this skill is
   overkill and offer to do it directly. A small change: a plan with one or
   two change areas, still reviewed. A project: the full plan below. If it
   grows mid-way, stop, say so, and step up a size.
1. **Capture intent.** One paragraph stating what the change must accomplish
   and why, from the user's words and any linked tickets or files. List
   everything that is unclear.
2. **Explore the code.** Launch at most 5 `explore` subagents in parallel,
   one per distinct area (entry points, data and storage, config, tests, CI,
   external contracts, docs), each with the [explore prompt](#explore-prompt).
   Use direct search for narrow questions. Record `git rev-parse HEAD` and
   whether the working tree has uncommitted changes; the working tree is
   the baseline the plan builds on.
3. **Decompose.** Name each change area as *what changes, where, why*, then
   state the intended approach as assumptions: which modules, functions or
   classes change, the shape of new or changed contracts, data flow,
   migration strategy, libraries. Write them as `Assumes: ...` so the panel
   can challenge them; do not write code. Where two approaches are viable
   and the choice is user-owned, put it under **Open questions**; otherwise
   decide it and record a Decision with Status `default`, alternatives
   included.
4. **Surface risk.** Per area: difficulty, security, backward compatibility
   and migration, data integrity, performance, observability, test gaps,
   dependencies between areas, and anything only domain knowledge can
   answer. Then write **Review focus**: the five input classes or failure
   modes the intent implies but nothing in the plan yet verifies, most
   likely to bite a user first.
5. **Gate.** If the draft has more than 8 change areas or spans several
   repositories, ask the user to split the task or approve a phased plan.
   Apply the ask-the-user rule to the open questions and the question
   lifecycle to the answers.
6. **Write the draft plan** from the [plan template](#plan-template) to
   `~/.cursor/plans/<kebab-slug>.plan.md`, unless the user names a path or
   the repo has a `plans/` or `docs/plans/` directory. If the file exists
   and the user did not name it, add a numeric suffix; never overwrite. Read
   the file back once, then tell the user the path.

## Phase 2 - Multi-model plan review

### Panel

| Short name | Slug |
| --- | --- |
| `sonnet` | `claude-sonnet-5-5-high` |
| `sol` | `gpt-5.6-sol-medium` |
| `opus` | `claude-opus-5-5-medium` |

Seats were resolved in Phase 0. If `Task` rejects a slug at launch, treat it
as the same gate: ask once whether to drop the seat or use the named
same-family alternative, then relaunch that reviewer only.

### Severity

| Severity | Meaning for a plan | Required action |
| --- | --- | --- |
| `critical` | Executing the plan as written would break current behavior, lose data, open a security hole, or build the wrong thing | Must be resolved in the plan before handoff |
| `warning` | Likely rework, edge-case bugs, hard-to-review PRs, or a gap a reviewer would block on | Resolve, or reject with a one-line reason that lands in the Review log's Not applied table |
| `nit` | Wording, ordering, small omissions | Orchestrator's discretion |

### Launch

In one turn, launch every seated reviewer in parallel as a `generalPurpose`
subagent with `model` set to its slug, `description` set to
`Plan reviewer <short name>`, and the [reviewer prompt](#reviewer-prompt).
Use the identical prompt for all of them; diversity comes from the models.
In Multitask mode set `run_in_background: true`.

Synthesis starts only when every seated reviewer has returned or exhausted
its retry. Per reviewer:

- Failed before returning: retry once with the same prompt.
- Returned prose, fenced or truncated JSON: strip code fences; if still not
  valid JSON with the documented keys, retry once with the original prompt
  plus "your previous output was not valid JSON; return only the JSON
  object". After that, treat the text as prose findings tagged lone and
  assign each a severity (capped at `warning`) and category yourself.
- Still missing: name it in the synthesis header. With fewer than two
  reviewers returned, tag every finding lone and state that consensus was
  not possible.

### Synthesize (orchestrator)

The parent agent merges findings; it does not act as another reviewer.

1. Match findings by underlying issue; same issue with different wording,
   section or severity still matches.
2. Verify each finding against the code and the plan. Drop findings whose
   evidence does not hold.
3. Tag each as **consensus** (2+ reviewers) or **lone**. **Promotion rule:**
   a consensus finding moves up one severity (`nit` to `warning`, `warning`
   to `critical`). When matched findings propose incompatible changes, keep
   the one with more agreement and record the other under Disagreements;
   with equal agreement and a user-owned choice, make it a question instead
   of a proposal.
4. Classify after promotion, first rule that matches wins: unverified or
   wrong is **dismissed**; out of scope is **noted**; contradicts a Decision
   with Status `decided (user)` is a **question** for the user, never
   auto-accepted; `critical` is **accepted**; `warning` is **accepted** or
   **rejected** by the orchestrator with a one-line reason; `nit` is
   **noted**.
5. Turn every accepted finding into a numbered proposal in the form
   `<n>. [<reviewers>] <plan section> - <what the plan should say>`. Dedupe
   the reviewers' `questions_for_user` with the questions from steps 3-4
   and keep those that meet the ask-the-user rule.
6. Present the [synthesis](#synthesis-format) to the user. Ask the kept
   questions and any proposal that touches a user-owned decision; apply the
   question lifecycle to the answers. If there are none, continue to
   Phase 3 without waiting.

## Phase 3 - Strengthen the plan

1. Apply the proposals yourself when there are 5 or fewer and none needs new
   code exploration. Otherwise delegate to one `generalPurpose` subagent
   (model: the Phase 0 planning model when available in this session, else
   inherit) with the [strengthener prompt](#strengthener-prompt). The
   strengthener receives accepted proposals, the Not applied table and user
   decisions; never delegate a decision the user or the orchestrator has
   not made.
2. The strengthened plan keeps the template and fills **Milestones**,
   **Tasks**, **Review log** and **PR description**; **Open questions**
   must be empty (question lifecycle applied to any that remain). Every
   Review focus line is pinned to the task that owns the code as a
   Verification entry.
3. **Self-review** before reporting, with the intent in front of you; fix
   inline, no second pass:
   - Coverage: every requirement in Intent and every change area maps to a
     task; every accepted proposal is reflected (grep the plan).
   - Consistency: names, contracts and `Assumes:` lines agree across change
     areas and tasks (a contract called one thing in CA2 and another in T5
     is a bug); every `Consumes:` has a matching `Produces:`.
   - Lines that decide nothing ("handle edge cases", "add validation",
     "TBD") are gaps: replace or remove them.
   - Proportion: a plan longer than the change it describes has started
     writing the code; cut detail that the implementer can decide alone.
     No task contains implementation code (commands under Verification are
     fine).
   - Every task has acceptance criteria, verification and interfaces; every
     Review focus line is pinned; Open questions is empty.
   - Each proposal the strengthener reported `not applied`: apply it
     yourself when the reason is mechanical; when it needs a new decision,
     ask the user in one batch or record a Decision with Status `pending`.
4. **Handoff.** Report plan path, milestones, task titles, decisions
   pending, and the plan's PR description block verbatim. Then ask the user
   to review the plan and choose how it will be executed, with one
   recommendation and a one-sentence reason (how much the tasks depend on
   each other's interfaces, how many there are, what a shipped mistake
   would cost): **subagent-driven** (a fresh implementer per task, a fresh
   reviewer after each, a whole-branch review at the end; most thorough,
   costs a fresh context per task) or **native** (this session implements
   every task, one reviewer on the whole branch at the end; cheapest).
   Stop. Implementation is a separate request.

## Red flags

| Thought | Reality |
| --- | --- |
| "The tasks are obvious, skip the panel" | Obvious to the author is the blind spot the panel exists for. |
| "I'll fill in sensible defaults" | Good. Write them down and say them. A default the user never heard is one they could not reject. |
| "No reviewer found anything" | Check the prompt reached them with the plan path and code state; an empty panel on a non-trivial plan is a launch failure, not a verdict. |
| "This finding restates the plan" | Not a finding. Dismiss it with that reason. |
| "The user approved the idea" | Approval covers what they saw. A plan section they have not read is not approved. |
| "I'll decide this one for them" | If it is in the ask-the-user list, ask. Batch it, do not skip it. |

## Plan template

```markdown
# <Title>

Preflight: <planning slug (role) | unavailable> | Code state: <HEAD sha>, <clean | uncommitted changes>

## Intent
<one paragraph: what must change and why>

## Context
- Entry points / affected modules: `path` - current behavior
- Tests and CI touching this area: `path`
- External contracts (APIs, schemas, configs, consumers): ...

## Scope
In: ...
Out: ...

## Assumptions
- A1 ...

## Open questions
- Q1 ... (not yet asked)

## Decisions
### D1 <title>
Status: decided (user) | default | pending
Context: <why a choice is needed, one or two sentences>
Decision: <what was chosen, or the default taken while pending>
Alternatives considered: <one line each, why not>
Consequences: <positive / negative; the trade-off accepted>

## Change areas
### CA1 <name>
What / where / why. Depends on: - | Decisions: D1
Assumes: <modules and symbols touched, contract shape, data flow, migration, libraries>

## Risks and concerns
| # | Area | Concern | Kind | Mitigation idea |
| --- | --- | --- | --- | --- |
Kind: difficulty, security, compat, migration, data, perf, observability, test-gap, dependency, other

## Review focus
<up to five lines: input class or failure mode the intent implies but nothing verifies yet, and the behavior a reasonable person expects; most likely first. In Phase 3 each line is pinned to the owning task's Verification.>

## Perspectives
- Dev: ...
- QA: how it is verified; what is hard to test; which regressions to guard
- PM/PO: user-visible outcome; acceptance; what "done" means

## Verification strategy
...

## Milestones            <!-- Phase 3 -->
1. M1 <name> - exit criteria

## Tasks                 <!-- Phase 3; titles are PR-ready: separate PRs, or the checklist of one PR -->
### T1 <imperative PR title, e.g. "auth: validate token expiry before session lookup">
Milestone: M1 | Areas: CA1 | Depends on: -
Scope: ...
Interfaces:
- Consumes: <what this task uses from earlier tasks: exact names and types>
- Produces: <what later tasks rely on: exact names and types>
Acceptance criteria: ...
Verification: <tests or commands; includes pinned Review focus lines>
Risks: ...

## Review log            <!-- Phase 3 -->
| Proposal | Reviewers | Applied to |
| --- | --- | --- |
Not applied: <Not applied table from the synthesis, verbatim>

## PR description        <!-- Phase 3; paste-ready -->
<title>

<one-paragraph summary from Intent>

Milestones: M1 ..., M2 ...
- [ ] T1 <title>
- [ ] T2 <title>
```

## Explore prompt

```text
Read-only exploration; do not edit any file.

Repository: <absolute repo path>
Task being planned: <verbatim user request>
Your area: <one area, e.g. "config loading and env resolution">
Questions: <specific questions for this area>

Return bullets only: `path:lines - current behavior` for everything relevant
to the task in your area, then `Unknowns:` (what you could not determine) and
`Also inspect:` (adjacent areas worth a look). No design proposals.
```

## Reviewer prompt

```text
You are one independent reviewer of an implementation plan. Read-only: do not
edit any file and do not implement anything.

Repository: <absolute repo path>
Code state: <HEAD sha>, <clean | uncommitted changes present>; treat the
working tree, including uncommitted changes, as the current code the plan
builds on.
Plan: <absolute plan path>
Intent: <intent paragraph>
Files named in the plan: <list from Context and Change areas>

Read the plan in full, then every file it names and their direct neighbors
(callers, schemas, tests, contracts) so you can verify its claims. Each
change area states its coding approach as `Assumes:` lines; challenge them
against the code (wrong module, contract that cannot hold, migration that
breaks consumers, library that does not fit) and name the better assumption.
Do not report the absence of code itself. Decisions with Status
`decided (user)` are the user's: do not propose changing them; if one is
unsafe, raise it under questions_for_user with evidence. Milestones and
tasks are added after your review; put splitting or ordering constraints
under `sequencing`.

Review adversarially as a senior developer, a QA engineer and a product
owner would. Look for: wrong assumptions about the current code, missing
change areas, unaddressed risks (security, backward compatibility,
migration, data integrity, performance, observability), design flaws,
sequencing problems, scope that is ambiguous or quietly widened or narrowed,
verification gaps (a Review focus line nothing will test), and anything
that would make the resulting pull requests hard to review.

Severity: critical = executing the plan as written breaks current behavior,
loses data, opens a security hole or builds the wrong thing; warning =
likely rework, edge-case bugs, hard-to-review PRs or a gap a reviewer would
block on; nit = wording, ordering, small omissions.

Not findings: restating what the plan says; "looks good" without having
read the code; hedged wording ("might possibly") where you have evidence,
state the consequence plainly. Propose what the plan should say, including
corrected `Assumes:` lines; do not write code.

Return JSON and nothing else:
{
  "findings": [
    {
      "severity": "critical" | "warning" | "nit",
      "category": "wrong-assumption" | "missing-area" | "design-flaw" | "sequencing" | "scope" | "verification" | "security" | "compat" | "risk",
      "plan_section": "Change areas / CA2",
      "evidence": "relative/path.py:40-58 - what the code does; or the plan section, doc path or absent artifact that proves it",
      "issue": "one or two sentences",
      "proposal": "what the plan should add or change"
    }
  ],
  "questions_for_user": ["only decisions the plan author cannot make alone"],
  "strengths": ["at most 3, one line each"]
}
`risk` is for risks not covered by the other categories. At most 15
findings, highest severity first. Return "findings": [] only when you read
the code and the plan holds.
```

## Strengthener prompt

```text
Revise the implementation plan at <absolute plan path> in place.

Repository: <absolute repo path>
Code state: <HEAD sha>, <clean | uncommitted changes present>
Accepted proposals, apply all, format `<n>. [<reviewers>] <section> - <change>`:
<numbered list>
Not applied table (copy verbatim under Review log, do not act on it):
<table>
User decisions: <answers from the user>

Read the plan in full first. Rules: keep the template and section order.
Update `Assumes:` lines where a proposal changes the approach; do not write
code. Do not add or remove change areas, Scope items, Assumptions or
Decisions except as a proposal directs; never change a Decision with Status
`decided (user)`. Fill Milestones (ordered, each with exit criteria), Tasks
(imperative titles usable as PR titles, each with Milestone, Areas, Depends
on, Scope, Interfaces with Consumes/Produces in exact names and types,
Acceptance criteria, Verification, Risks; every change area covered by at
least one task; every Review focus line pinned to the owning task's
Verification), Review log (one row per accepted proposal, with its
reviewers, plus the Not applied table), and PR description. If tasking
needs a choice the plan does not settle, add a Decision with Status
`pending` instead of choosing. Open questions must be empty: an answered
one becomes a Decision with Status `decided (user)`; anything else becomes
a Decision with Status `pending` holding the default taken. Read the
referenced code when a proposal needs it. Do not edit any other file.
Return one line per proposal: `<n>: applied to <section>` or
`<n>: not applied - <reason>`.
```

## Synthesis format

```markdown
### Review synthesis - <plan path>
Reviewers: sonnet, sol, opus (skipped or failed: ...)

| # | Sev (after promotion) | Category | Plan section | Finding | Agreed by | Decision |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | critical | wrong-assumption | Context | Plan assumes X; `path:line` does Y | sonnet, opus | accepted |

Disagreements: <incompatible proposals and which one was kept>
Contradicts decided (user) items: <finding numbers, turned into questions below>

### Proposals
1. [sonnet, opus] <section> - <what changes>

### Not applied
| # | Reviewers | Classification | Reason |
| --- | --- | --- | --- |
| 4 | sol | rejected | ... |
Omitted: <n> duplicates, <n> unverified, <n> nits noted.

### Questions for you
- ...
```
