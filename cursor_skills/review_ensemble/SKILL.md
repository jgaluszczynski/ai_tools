---
name: review-ensemble
description: >-
  Run a multi-model code review: launch Sonnet 5.5, GPT 5.6 Sol, Opus 5.5,
  and the highest available Fable (5.3, else 5.1) as parallel read-only
  reviewers on the same diff, run
  Bugbot and Security Review alongside them, then merge every finding into
  one deduplicated findings table with numbered fix proposals so most GitHub
  review comments are closed in a single implementation pass. Use when the
  user asks for an ensemble review, a multi-model review, or names this
  skill.
disable-model-invocation: true
---

# Review Ensemble

Six reviewers find more real issues than one. The merge step turns that
extra recall back into one fix per issue, so the author does not face a
second round of duplicates and nits on GitHub.

Output is a findings table and fix proposals. Do not edit code, post GitHub
comments, or open a pull request unless the user asks for that next.

## Reviewers

Six reviewers run in parallel. Before launching, resolve every model slug
against the list of models available in this session (the
`available_subagent_models` list). Use a slug only if it appears there
verbatim. Skip any seat whose slug is unavailable, do not substitute another
model, and tell the user which seats were skipped.

Model panel, each a `generalPurpose` subagent with `model` set to the slug:

| Short name | Slug | Why it is on the panel |
| --- | --- | --- |
| `sonnet` | `claude-sonnet-5-5-high` | Highest intelligence index of the group |
| `sol` | `gpt-5.6-sol-medium` | Highest coding index of the group |
| `opus` | `claude-opus-5-5-medium` | Strongest Anthropic generalist, different tier from Sonnet |
| `fable` | highest available Fable, see below | Current strong pick for coding and planning |

The `fable` seat is the only one with a fallback. Resolve it in this order
and stop at the first slug that is available:

1. `claude-fable-5-3-thinking-high`
2. `claude-fable-5-1-thinking-high`

Name the resolved slug when launching. If neither is available, skip the
seat and say so. No other substitution is allowed in any seat.

Complementary reviewers, each with its own subagent type:

| Short name | Subagent type | Description |
| --- | --- | --- |
| `bugbot` | `bugbot` | `Bugbot` |
| `security` | `security-review` | `Security Review` |

If `bugbot` or `security-review` is not an available subagent type, skip it
and say so. Do not review in place for it; the model panel covers that.

## Merger

The parent agent (this chat) merges. It is a synthesis step and does not act
as a seventh reviewer. If the chat model differs from the slug resolved for
the `fable` seat, say so once before launching; that slug is the current
strong pick for planning and coding, and the merge is synthesis plus precise
edit instructions. The chat model running the merge and the `fable` reviewer
being the same model is expected and is not a reason to skip the seat.

## Run

1. Record the SHAs every model reviewer must use:

   ```bash
   git rev-parse HEAD
   git merge-base HEAD "$(git symbolic-ref --short refs/remotes/origin/HEAD)"
   ```

   If `refs/remotes/origin/HEAD` is unset, use `origin/main` or ask the user
   for the base branch.

   Review `merge-base..HEAD` plus the working tree by default. The working
   tree includes untracked files, which `git diff` does not show; reviewers
   list them with `git status --short --untracked-files=all` and read them
   in full. When the user asks for uncommitted changes only, use `git diff
   HEAD` plus untracked files and say so in every prompt.
2. In one turn, launch all six available reviewers in parallel:
   - Four model reviewers with the [model reviewer prompt](#model-reviewer-prompt),
     `description` set to `Reviewer <short name>`. Change only the repository
     path, SHAs, and diff mode between them.
   - `bugbot` with `description: "Bugbot"` and `security-review` with
     `description: "Security Review"`, both using the
     [complementary reviewer prompt](#complementary-reviewer-prompt). These
     compute the diff themselves from the repository path. Do not pass SHAs.
   In Multitask mode set `run_in_background: true` on all of them.
3. If a reviewer fails before returning findings, retry that one reviewer
   once with the same prompt. If Bugbot reports it could not compute the
   diff, retry it once with `Diff: natural language` and a `Change
   Description` listing each changed file. Then merge whoever returned and
   name any reviewer that is missing from the merge.

## Model reviewer prompt

```text
You are one reviewer on a panel. Review the code change below and return
findings only. Do not edit files, do not run formatters, do not post
anything to GitHub, do not fix anything.

Repository: <absolute repository path>
Base SHA: <merge-base sha>
Head SHA: <head sha>
Diff mode: <"branch changes incl. working tree" | "uncommitted changes only">

Compute the diff from those SHAs yourself (git diff <base>..<head> plus
`git diff HEAD` for the working tree in branch mode; `git diff HEAD` only in
uncommitted mode). In both modes also run
`git status --short --untracked-files=all` and read every untracked file in
full, treating it as added. Read surrounding files when needed to verify a
claim.

Report an issue only if it is true (verifiable against the changed code),
relevant (fixing it improves this change), non-trivial, and inside the
diff. Skip style, formatting, naming, and comments. Skip pre-existing
issues the change does not touch.

Return a JSON array and nothing else, at most 15 items, highest severity
first:
[
  {
    "severity": "high" | "medium" | "low",
    "category": "correctness" | "security" | "reliability" | "performance" | "api" | "tests",
    "file": "relative/path.py",
    "lines": "40-58",
    "issue": "one or two sentences on what is wrong",
    "evidence": "the specific lines or behavior in the diff that prove it",
    "fix": "the concrete change that resolves it"
  }
]
Return [] when you find nothing that meets the bar.
```

## Complementary reviewer prompt

Same shape for both. Bugbot also accepts `natural language` on retry.

```text
Full Repository Path: <absolute repository path>
Diff: <"branch changes" | "uncommitted changes">
```

Their findings arrive as a table with Severity, Location (`file:line`), and
Finding. Normalize each row into the model schema before merging: map
Severity to `high`/`medium`/`low`, split Location into `file` and `lines`,
use Finding as `issue`, set `category` to `security` for Security Review
rows and infer it for Bugbot rows, and write the `fix` yourself from the
finding text and the code.

## Merge rules

Match findings by underlying issue. Two findings match when they describe
the same defect even if the wording, line range, or severity differ.

- One row per issue. Overlapping findings become one row and their fixes
  become one proposal.
- Keep a row when two or more reviewers agree, or when one reviewer marks
  it `high` and its evidence points at changed lines. Bugbot and Security
  Review count as reviewers for agreement.
- Drop single-reviewer `low` findings and anything outside the diff.
- Drop any finding whose evidence does not hold when you check the code.
- When two fixes contradict, keep the one with more agreement and state
  that the other was dropped.
- Order: `high` correctness, security, and reliability first, then
  `medium`, then the rest.

## Output

Print exactly these sections.

### Findings

| # | Sev | Category | Location | Finding | Agreed by |
| --- | --- | --- | --- | --- | --- |
| 1 | high | correctness | `src/auth.py:40-58` | Token expiry checked after DB lookup, expired tokens hit the database | sonnet, sol, bugbot |
| 2 | medium | security | `src/api.py:112` | Path from query string joined without normalization | security, fable |

Use the short names from the reviewer tables in `Agreed by`. Keep each
Finding to one sentence.

### Fixes

One block per row, same number as the table:

```markdown
#### 1. `src/auth.py:40-58` - check token expiry before the DB lookup
Change: move the `expires_at < now()` guard above `session_repo.get()` and
return `AuthError.expired` there.
Verify: `pytest tests/test_auth.py -k expired`
```

Keep each block to Change and Verify. Put short code in the Change line
when it is clearer than prose.

### Verify all

One list of tests or commands that covers every fix.

### Coverage

- `Omitted N findings (M duplicates, K single-reviewer low, J unverified, I out of diff).`
- Reviewers that reported, and any that were skipped or failed, or
  `All six reviewers reported.`
- The slug resolved for the `fable` seat.

Never claim the panel is the best set of reviewers for this repository.
