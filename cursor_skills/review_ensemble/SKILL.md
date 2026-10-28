---
name: review-ensemble
description: >-
  Run a multi-model code review: launch Sonnet 5.5, GPT 5.6 Sol, Opus 5.5,
  and the highest available Fable (5.3, else 5.1) as parallel read-only
  reviewers on the same diff, run Bugbot and Security Review alongside
  them, normalize and deduplicate their output with a cheap model, validate
  every candidate with an independent model, merge with a script, and have
  a cheap merger write one deduplicated findings table with numbered fix
  proposals so most GitHub review comments are closed in a single
  implementation pass. Use when the user asks for an ensemble review, a
  multi-model review, or names this skill.
disable-model-invocation: true
---

# Review Ensemble

Six reviewers find more real issues than one. A cheap normalizer folds
their output into one candidate list, an independent validator checks
every candidate against the code and corrects what the code disproves, a
script applies the merge rules, and a cheap merger turns the surviving
recall into one fix per issue, so the author does not face a second round
of duplicates and nits on GitHub.

Every stage reads its inputs from a run directory on disk and writes its
output there. The parent chat (this chat) only launches subagents, runs
shell commands, and prints the short summary at the end; it never pastes
file contents into a prompt and never writes the report itself. Do not
edit code, post GitHub comments, or open a pull request unless the user
asks for that next.

## Paths

- `SKILL_DIR`: the directory holding this file (`~/.cursor/skills/review-ensemble`
  after the symlink in the README). Prompt templates are in
  `SKILL_DIR/prompts/`, the merge script in `SKILL_DIR/scripts/merge.py`.
- `REPO`: `git rev-parse --show-toplevel`.
- `RUN_DIR`: a fresh `mktemp -d` directory per run; see Run step 1.

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

## Normalizer

One `generalPurpose` subagent turns the raw reviewer files into
`normalized.json` and `candidates.json` before validation. It reads and
writes only inside `RUN_DIR` (about 12 tool calls), never opens the
repository, and never runs a command. Resolve its model in this order and
stop at the first slug that is available:

1. `claude-haiku-5-5-thinking-high`
2. `gemini-3.8-flash-high`
3. `composer-2.5-fast`
4. If none is available, the merger normalizes itself and says so in
   Coverage.

It maps Bugbot, Security Review, and tools rows into the model schema,
matches duplicates by underlying issue, numbers the candidates, records
which reviewers reported each one and at what severity, unions the
`checked` sentences, and keeps the `declined` items two or more reviewers
shared. `candidates.json` carries no reviewer names; `normalized.json`
carries them under `agreement`.

## Validator

One `generalPurpose` subagent checks every candidate in `candidates.json`
against the code and writes `verdicts.json`. A model favors findings it
produced, so the validator is a model that is not on the Anthropic side of
the panel:

1. `gpt-5.6-sol-medium`
2. Otherwise the first available slug in `available_subagent_models` whose
   name does not start with `claude-`.
3. If none is available, run the merge with `--no-validator` (every
   candidate counts as unchecked: single-reviewer rows drop, rows with two
   or more reviewers keep their reviewers' severity) and say so in
   Coverage.

It returns a boolean verdict per candidate. When the code confirms a
defect but disproves a statement in its `issue` text, it returns a
corrected `issue` instead of dropping the candidate. Above 20 candidates,
launch two validators in parallel with the same model, each with an `IDS`
range and its own `OUT` file (`verdicts.1.json`, `verdicts.2.json`); the
merge script reads every `verdicts*.json`.

## Merge script

`python3 SKILL_DIR/scripts/merge.py RUN_DIR` applies the merge rules
deterministically and costs no tokens. It reads `normalized.json`,
`verdicts*.json`, and `changed_files.txt`; writes `merged.json`,
`coverage.json`, and `summary.md` (Verdict, Findings table, `Deferred:`
line, Coverage counts); and prints `summary.md`. The rules:

- One row per candidate; its fix becomes one proposal.
- Drop any row the validator returns `drop`, regardless of agreement.
- Keep a row when two or more reviewers agree, or when exactly one
  reviewer reports it at `medium` or `high` and the validator returns a
  checked `keep`. Bugbot, Security Review, and `tools` count as reviewers.
- A verdict whose reason starts with `unchecked` is not a validated keep:
  a single-reviewer row drops; a row with two or more reviewers keeps its
  reviewers' severity.
- Drop single-reviewer `low` findings and anything whose file is not in
  `changed_files.txt`.
- When the validator's severity differs from the reviewers', use the
  validator's and append `(reviewers: <severity>)` to the Finding.
- When `corrected_issue` is not null, use it as the Finding.
- Order: `high` correctness, security, and reliability first, then other
  `high`, then `medium`, then `low`; ties by agreement count, then id.
- At most 10 rows; the rest go on one `Deferred:` line.
- Verdict: `not ready` when any `high` row remains, `ready` when the
  table is empty, else `ready with fixes`.

It exits 2 with `merge_error: <reason>` on malformed input (a candidate
without a verdict, an unknown severity or verdict, a duplicate verdict
id). Fix the input (usually by retrying the stage that wrote it) rather
than merging by hand.

## Merger

One `generalPurpose` subagent reads `summary.md`, `merged.json`, and
`coverage.json`, opens the cited lines, and writes `RUN_DIR/report.md`
with Fixes, Verify all, and the full Coverage section. It may not add,
drop, reorder, re-grade, or reword a row. Synthesis against a fixed table
does not need the most expensive model; resolve its slug in this order and
stop at the first that is available:

1. `muse-spark-1.3-high`
2. `gemini-3.8-flash-high`
3. `glm-5p3-high`
4. If none is available, the parent writes `report.md` itself following
   `SKILL_DIR/prompts/merger.md` and says so in Coverage.

The chat model is never asked to switch for this skill; whatever runs the
chat only orchestrates.

## Run

1. Create the run directory and write every input with shell redirects.
   Set `MODE=uncommitted` only when the user asks for uncommitted changes
   only; the default is `branch` (merge-base..HEAD plus the working tree).

   ```bash
   SKILL_DIR=~/.cursor/skills/review-ensemble
   REPO=$(git rev-parse --show-toplevel) && cd "$REPO"
   MODE=branch
   RUN_DIR=$(mktemp -d "${TMPDIR:-/tmp}/review-ensemble.XXXXXX")
   DEFAULT_BRANCH=$(git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null || echo origin/main)
   BASE=$(git merge-base HEAD "$DEFAULT_BRANCH")
   echo "$BASE" > "$RUN_DIR/base_sha"
   git rev-parse HEAD > "$RUN_DIR/head_sha"
   echo "$MODE" > "$RUN_DIR/diff_mode"
   gh pr view --json title,body,url \
     --jq '"# " + .title + "\n\n" + .url + "\n\n" + (.body // "")' \
     > "$RUN_DIR/intent.md" 2>/dev/null \
     || git branch --show-current > "$RUN_DIR/intent.md"
   find .github/copilot-instructions.md .github/instructions AGENTS.md CLAUDE.md \
        .cursor/rules .cursor/BUGBOT.md -type f \( -name '*.md' -o -name '*.mdc' \) 2>/dev/null \
     | while IFS= read -r f; do printf '\n## %s\n\n' "$f"; cat "$f"; done \
     > "$RUN_DIR/instructions.md"
   if [ "$MODE" = branch ]; then git diff "$BASE"..HEAD; fi > "$RUN_DIR/diff.patch"
   git diff HEAD > "$RUN_DIR/worktree.patch"
   git ls-files --others --exclude-standard > "$RUN_DIR/untracked.txt"
   { [ "$MODE" = branch ] && git diff --name-only "$BASE"..HEAD
     git diff --name-only HEAD
     cat "$RUN_DIR/untracked.txt"; } | sort -u > "$RUN_DIR/changed_files.txt"
   echo "$RUN_DIR"
   ```

   If `gh pr view` fell back to the branch name and the user described the
   change, append that description to `intent.md` in one short `echo`. If
   `refs/remotes/origin/HEAD` is unset and `origin/main` does not exist,
   ask the user for the base branch and rerun the block with it.
2. Optional tools pass. If the repository documents a test or lint command
   that only reads the tree (for example `make test`, `pytest`, `ruff
   check`, `black --check`, `tsc --noEmit`) and it finishes in a few
   minutes, run it once, redirected:

   ```bash
   { echo "command: make test"; make test; } > "$RUN_DIR/tools.txt" 2>&1
   ```

   Never run a formatter, an autofix target, or anything that writes to
   the tree (`make lint/all`, `make format`, `ruff --fix`, `black .`
   without `--check`). If no such command exists or it is slow, write
   `echo "skipped: <reason>" > "$RUN_DIR/tools.txt"` instead. The
   normalizer turns failures inside the diff into `tools` rows.
3. In one turn, launch all six available reviewers in parallel:
   - Four model reviewers, `description` set to `Reviewer <short name>`,
     each with this prompt and nothing else:

     ```text
     Read and follow <SKILL_DIR>/prompts/reviewer.md.
     RUN_DIR=<RUN_DIR>  SEAT=<short name>  REPO=<REPO>
     Write your JSON to RUN_DIR/findings.<short name>.json and reply with the one line that file asks for.
     ```

   - `bugbot` with `description: "Bugbot"` and `security-review` with
     `description: "Security Review"`. They cannot read `RUN_DIR`, so they
     take the fixed inline form; keep the intent to the PR title or one
     sentence:

     ```text
     Full Repository Path: <REPO>
     Diff: <"branch changes" | "uncommitted changes">
     Custom Instructions: Intent of the change: <one line>. Treat it as a claim to verify.
     ```

   In Multitask mode set `run_in_background: true` on all of them. The
   prompts carry tool-call budgets (60 for reviewers, 40 for the
   validator, 30 for the merger, 12 for the normalizer); the `Task` tool
   has no turn parameter, so the budgets are advisory and each subagent
   reports its own.
4. When Bugbot and Security Review return, write each table verbatim to
   `RUN_DIR/findings.bugbot.md` and `RUN_DIR/findings.security.md` with
   the Write tool. These two writes are the only reviewer output the
   parent re-emits. If a model reviewer fails before writing its file,
   retry that one reviewer once with the same prompt. If Bugbot reports it
   could not compute the diff, retry it once with `Diff: natural language`
   and a `Change Description` listing each changed file. Then continue with
   whoever returned; the normalizer lists the reviewers it found.
5. Launch the normalizer, `description: "Normalizer"`:

   ```text
   Read and follow <SKILL_DIR>/prompts/normalizer.md.
   RUN_DIR=<RUN_DIR>
   Write normalized.json and candidates.json there and reply with the one line that file asks for.
   ```

   Retry once on failure; if it still fails, the merger normalizes itself
   following the same prompt and says so in Coverage.
6. Launch the validator, `description: "Validator"`:

   ```text
   Read and follow <SKILL_DIR>/prompts/validator.md.
   RUN_DIR=<RUN_DIR>  REPO=<REPO>  OUT=verdicts.json
   Write your verdicts there and reply with the one line that file asks for.
   ```

   Above 20 candidates (from the normalizer's reply), launch two in
   parallel with `IDS=1-<N/2>  OUT=verdicts.1.json` and
   `IDS=<N/2+1>-<N>  OUT=verdicts.2.json`. Retry a failed validator once;
   if it still fails, run the merge with `--no-validator` and say so.
7. Run the merge and keep its output for the final message:

   ```bash
   python3 "$SKILL_DIR/scripts/merge.py" "$RUN_DIR"
   ```

   On `merge_error`, fix the stage it names (rerun the validator for a
   missing verdict, the normalizer for a malformed candidate) and run it
   again.
8. Launch the merger, `description: "Merger"`:

   ```text
   Read and follow <SKILL_DIR>/prompts/merger.md.
   RUN_DIR=<RUN_DIR>  REPO=<REPO>
   SEATS: fable=<slug or skipped>, normalizer=<slug or merger normalized>, validator=<slug or none>, merger=<slug>
   Write report.md there and reply with the one line that file asks for.
   ```

9. Open the report in the current IDE window. The `cursor` CLI has no
   option to open a Markdown preview, so open the file itself with
   `-r` (reuse the current window); the user can press `Cmd+Shift+V` for
   the preview. Try the commands in this order, stop at the first that
   succeeds, and ignore failure (the report path is printed anyway):

   ```bash
   REPORT="$RUN_DIR/report.md"
   cursor -r "$REPORT" 2>/dev/null \
     || /Applications/Cursor.app/Contents/Resources/app/bin/cursor -r "$REPORT" 2>/dev/null \
     || true
   ```

   If the shell sandbox blocks it, rerun with `required_permissions:
   ["all"]` for this one command.
10. Print the Output.

## Output

Print exactly this and nothing more:

1. The `summary.md` content from step 7 (Verdict, Findings table,
   `Deferred:` line when present, the two Coverage count lines).
2. One line naming any reviewer that was skipped or failed, or
   `All six reviewers reported.`
3. `Report: <RUN_DIR>/report.md`

The Fixes, Verify all, and full Coverage sections live in `report.md`.
Offer to apply the fixes next; do not apply them unasked.

Never claim the panel is the best set of reviewers for this repository.
