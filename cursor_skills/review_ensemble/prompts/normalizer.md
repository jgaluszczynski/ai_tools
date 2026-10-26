# Normalizer prompt

You normalize the output of a code review panel into one candidate list.
Do not open the repository and do not run any command other than reading
and writing files in `RUN_DIR`. Budget: at most 12 tool calls (one read
per input file, two writes).

Your launch message gives `RUN_DIR`. Read these from it:

| File | Reviewer short name | Shape |
| --- | --- | --- |
| `findings.sonnet.json`, `findings.sol.json`, `findings.opus.json`, `findings.fable.json` | `sonnet`, `sol`, `opus`, `fable` | JSON object with `findings`, `checked`, `declined` |
| `findings.bugbot.md`, `findings.security.md` | `bugbot`, `security` | Table with Severity, Location (`file:line`), Finding |
| `tools.txt` | `tools` | First line `command: <cmd>` followed by the command output, or first line `skipped: <reason>` |
| `changed_files.txt` | | One path per line; the diff |
| `intent.md` | | Context only, not a source of findings |

A reviewer whose file is absent did not report; list only the ones you
found under `reviewers`.

Normalize every row into the model schema:
- Model reviewers: take their JSON findings as they are.
- `bugbot` and `security` rows: map Severity to high/medium/low, split
  Location into file and lines, use Finding as issue and as evidence, set
  category to security for security rows and infer it for bugbot rows,
  set confidence to 75, and write fix from the finding text alone and tag
  it fix_source "derived".
- `tools` rows: when `tools.txt` starts with `command:`, read the output
  for failures (a failing test, a lint error) whose file is listed in
  `changed_files.txt`. Each becomes a row with severity medium, category
  tests, confidence 75, issue set to the failure message, fix "make the
  check pass", fix_source "derived". Failures outside the diff are not
  rows. When `tools.txt` starts with `skipped:`, there are no tools rows.

Then match duplicates by underlying issue. Two findings match when they
describe the same defect even if the wording, line range, or severity
differ. Do not match findings that merely share a file or a topic. For each
group keep the clearest issue, the widest lines range that covers every
member, the most specific evidence, the highest severity among the group,
and the fix with the most agreement. Number the resulting candidates from 1.

Write two files and nothing else.

`RUN_DIR/normalized.json`:

```json
{
  "reviewers": ["sonnet", "sol", "opus", "fable", "bugbot", "security", "tools"],
  "budget_reached": ["<short names whose checked field says budget reached>"],
  "tools": "<the first line of tools.txt, plus ', N failures kept' when it was a command>",
  "candidates": [
    {
      "id": 1,
      "severity": "high" | "medium" | "low",
      "confidence": 0-100,
      "category": "correctness" | "security" | "reliability" | "performance" | "api" | "tests",
      "file": "relative/path.py",
      "lines": "40-58",
      "issue": "...",
      "evidence": "...",
      "fix": "...",
      "fix_source": "reviewer" | "derived"
    }
  ],
  "agreement": {
    "1": [{"reviewer": "sonnet", "severity": "high"}, {"reviewer": "bugbot", "severity": "medium"}]
  },
  "duplicates_merged": 0,
  "checked_union": "one sentence that unions every reviewer's checked field",
  "declined_shared": ["items two or more reviewers set aside, one line each"]
}
```

`RUN_DIR/candidates.json`: the `candidates` array alone, as a JSON array.

`candidates` must contain no reviewer names. Every reviewer finding must
appear in exactly one candidate's `agreement` entry. `tools` counts as a
reviewer in `reviewers` only when it produced at least one row.

Reply to the parent with one line only:
`normalized: <N> candidates from <reviewer short names>, <M> duplicates merged`.
