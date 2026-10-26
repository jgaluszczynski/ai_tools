"""Tests for the review-ensemble merge rules."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import merge  # noqa: E402

CHANGED = ["src/auth.py", "src/api.py", "src/jobs.py"]


def candidate(cid, severity="medium", **overrides):
    base = {
        "id": cid,
        "severity": severity,
        "confidence": 80,
        "category": "correctness",
        "file": "src/auth.py",
        "lines": f"{cid * 10}-{cid * 10 + 5}",
        "issue": f"Issue {cid} occurs on every input.",
        "evidence": f"line {cid * 10}",
        "fix": f"Fix {cid}",
        "fix_source": "reviewer",
    }
    base.update(overrides)
    return base


def verdict(cid, status="keep", **overrides):
    base = {
        "id": cid,
        "true_at_head": status == "keep",
        "verifiable": "src/auth.py:10" if status == "keep" else None,
        "actionable_specific": True,
        "author_would_fix": True,
        "generic": False,
        "severity": None,
        "corrected_issue": None,
        "verdict": status,
        "reason": "holds" if status == "keep" else "not true at head",
    }
    base.update(overrides)
    return base


def agree(*reviewers, severity="medium"):
    return [{"reviewer": r, "severity": severity} for r in reviewers]


def write_run(
    tmp_path,
    candidates,
    agreement,
    verdicts=None,
    changed=CHANGED,
    **normalized_extra,
):
    normalized = {
        "reviewers": ["sonnet", "sol", "opus", "fable", "bugbot", "security"],
        "budget_reached": [],
        "tools": "skipped: no read-only command",
        "candidates": candidates,
        "agreement": {str(k): v for k, v in agreement.items()},
        "duplicates_merged": 0,
        "checked_union": "read src/auth.py",
        "declined_shared": [],
    }
    normalized.update(normalized_extra)
    (tmp_path / "normalized.json").write_text(json.dumps(normalized))
    (tmp_path / "changed_files.txt").write_text("\n".join(changed) + "\n")
    if verdicts is not None:
        (tmp_path / "verdicts.json").write_text(json.dumps(verdicts))
    return tmp_path


def rows(out):
    return out["result"]["rows"]


def test_validator_drop_beats_agreement(tmp_path):
    run = write_run(
        tmp_path,
        [candidate(1, "high")],
        {1: agree("sonnet", "sol", "opus", severity="high")},
        [verdict(1, "drop")],
    )
    out = merge.run(run)
    assert rows(out) == []
    assert out["result"]["coverage"]["validator_dropped"] == 1
    assert out["result"]["verdict"]["status"] == "ready"


def test_two_reviewers_keep(tmp_path):
    run = write_run(
        tmp_path,
        [candidate(1, "low")],
        {1: agree("sonnet", "bugbot", severity="low")},
        [verdict(1)],
    )
    out = merge.run(run)
    assert [r["id"] for r in rows(out)] == [1]
    assert rows(out)[0]["agreed_by"] == ["sonnet", "bugbot"]


def test_single_medium_with_keep_keeps(tmp_path):
    run = write_run(
        tmp_path, [candidate(1, "medium")], {1: agree("opus")}, [verdict(1)]
    )
    out = merge.run(run)
    assert [r["id"] for r in rows(out)] == [1]
    assert out["result"]["verdict"]["status"] == "ready with fixes"


def test_single_low_drops_even_with_keep(tmp_path):
    run = write_run(
        tmp_path,
        [candidate(1, "low")],
        {1: agree("opus", severity="low")},
        [verdict(1)],
    )
    out = merge.run(run)
    assert rows(out) == []
    assert out["result"]["coverage"]["single_low"] == 1


def test_unchecked_budget_drops_single_keeps_multi(tmp_path):
    run = write_run(
        tmp_path,
        [candidate(1, "high"), candidate(2, "high")],
        {1: agree("sonnet", severity="high"), 2: agree("sol", "fable")},
        [
            verdict(
                1, reason="unchecked: budget", verifiable=None, severity=None
            ),
            verdict(
                2,
                reason="unchecked: budget",
                verifiable=None,
                severity="low",
            ),
        ],
    )
    out = merge.run(run)
    kept = rows(out)
    assert [r["id"] for r in kept] == [2]
    assert kept[0]["severity"] == "high"
    assert "(reviewers:" not in kept[0]["finding"]
    assert out["result"]["coverage"]["unchecked"] == 1


def test_validator_severity_overrides_with_suffix(tmp_path):
    run = write_run(
        tmp_path,
        [candidate(1, "high")],
        {1: agree("security", "fable", severity="high")},
        [verdict(1, severity="medium")],
    )
    out = merge.run(run)
    row = rows(out)[0]
    assert row["severity"] == "medium"
    assert row["finding"].endswith("(reviewers: high)")
    assert out["result"]["verdict"]["status"] == "ready with fixes"


def test_corrected_issue_replaces_text(tmp_path):
    run = write_run(
        tmp_path,
        [candidate(1, "medium")],
        {1: agree("sonnet")},
        [verdict(1, corrected_issue="Issue 1 occurs only when x is None.")],
    )
    out = merge.run(run)
    row = rows(out)[0]
    assert row["finding"] == "Issue 1 occurs only when x is None."
    assert row["corrected"] is True
    assert out["result"]["coverage"]["text_corrected"] == 1


def test_out_of_diff_drops_before_verdict_lookup(tmp_path):
    run = write_run(
        tmp_path,
        [candidate(1, "high", file="./src/other.py")],
        {1: agree("sonnet", "sol", severity="high")},
        [],
    )
    out = merge.run(run)
    assert rows(out) == []
    assert out["result"]["coverage"]["out_of_diff"] == 1


def test_leading_dot_slash_in_candidate_path_is_in_diff(tmp_path):
    run = write_run(
        tmp_path,
        [candidate(1, "medium", file="./src/auth.py")],
        {1: agree("sonnet", "sol")},
        [verdict(1)],
    )
    assert [r["id"] for r in rows(merge.run(run))] == [1]


def test_ordering_high_priority_categories_first(tmp_path):
    cands = [
        candidate(1, "medium", category="correctness"),
        candidate(2, "high", category="performance"),
        candidate(3, "high", category="security", file="src/api.py"),
        candidate(4, "low", category="tests", file="src/jobs.py"),
        candidate(5, "high", category="correctness", file="src/jobs.py"),
    ]
    agreement = {
        1: agree("sonnet", "sol"),
        2: agree("opus", "fable", severity="high"),
        3: agree("security", "sol", severity="high"),
        4: agree("sonnet", "bugbot", severity="low"),
        5: agree("sonnet", "sol", "opus", severity="high"),
    }
    verdicts = [verdict(c["id"]) for c in cands]
    run = write_run(tmp_path, cands, agreement, verdicts)
    out = merge.run(run)
    assert [r["id"] for r in rows(out)] == [5, 3, 2, 1, 4]
    assert [r["n"] for r in rows(out)] == [1, 2, 3, 4, 5]
    assert out["result"]["verdict"] == {
        "status": "not ready",
        "sentence": "Rows 1, 2, 3 are high.",
    }


def test_cap_ten_rows_and_deferred_line(tmp_path):
    ids = list(range(1, 14))
    cands = [candidate(i, "low") for i in ids]
    agreement = {i: agree("sonnet", "sol", severity="low") for i in ids}
    run = write_run(tmp_path, cands, agreement, [verdict(i) for i in ids])
    out = merge.run(run)
    assert len(rows(out)) == 10
    assert [r["id"] for r in out["result"]["deferred"]] == [11, 12, 13]
    assert "Deferred: `src/auth.py:110-115`" in out["summary"]
    assert "| 10 | low |" in out["summary"]
    assert "| 11 |" not in out["summary"]


def test_no_validator_mode_applies_unchecked_rule(tmp_path):
    run = write_run(
        tmp_path,
        [candidate(1, "high"), candidate(2, "high")],
        {1: agree("sonnet", severity="high"), 2: agree("sol", "fable")},
    )
    out = merge.run(run, no_validator=True)
    assert [r["id"] for r in rows(out)] == [2]
    assert out["coverage"]["validator"] == "none (--no-validator)"


def test_summary_and_files_written(tmp_path):
    run = write_run(
        tmp_path,
        [candidate(1, "medium", issue="Pipe | in text")],
        {1: agree("sonnet", "sol")},
        [verdict(1)],
        duplicates_merged=3,
        budget_reached=["opus"],
    )
    out = merge.run(run)
    summary = (run / "summary.md").read_text()
    assert summary == out["summary"]
    assert summary.startswith("### Verdict\n\nready with fixes: Rows 1")
    assert "| `src/auth.py:10-15` | Pipe \\| in text | sonnet, sol |" in summary
    assert (
        "Omitted 3 findings (3 duplicates, 0 single-reviewer low, "
        "0 validator dropped, 0 unchecked (budget), 0 out of diff)."
    ) in summary
    assert "Text corrected: 0 rows." in summary
    merged = json.loads((run / "merged.json").read_text())
    assert merged["rows"][0]["n"] == 1
    coverage = json.loads((run / "coverage.json").read_text())
    assert coverage["budget_reached"] == ["opus"]
    assert coverage["duplicates"] == 3


def test_empty_table_renders_ready(tmp_path):
    run = write_run(tmp_path, [], {}, [])
    out = merge.run(run)
    assert "ready: No finding survived" in out["summary"]
    assert "No findings." in out["summary"]


def test_split_verdict_files_are_merged(tmp_path):
    run = write_run(
        tmp_path,
        [candidate(1, "medium"), candidate(2, "medium")],
        {1: agree("sonnet", "sol"), 2: agree("opus", "fable")},
    )
    (run / "verdicts.1.json").write_text(json.dumps([verdict(1)]))
    (run / "verdicts.2.json").write_text(json.dumps([verdict(2, "drop")]))
    out = merge.run(run)
    assert [r["id"] for r in rows(out)] == [1]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c, v: v.clear(),
        lambda c, v: c[0].__setitem__("severity", "critical"),
        lambda c, v: c[0].pop("fix"),
        lambda c, v: v[0].__setitem__("verdict", "maybe"),
        lambda c, v: v.append(dict(v[0])),
    ],
    ids=[
        "missing-verdict",
        "unknown-severity",
        "missing-candidate-key",
        "unknown-verdict",
        "duplicate-verdict-id",
    ],
)
def test_malformed_input_exits_nonzero(tmp_path, capsys, mutate):
    cands = [candidate(1, "medium")]
    verdicts = [verdict(1)]
    mutate(cands, verdicts)
    run = write_run(tmp_path, cands, {1: agree("sonnet", "sol")}, verdicts)
    assert merge.main([str(run)]) == 2
    assert "merge_error:" in capsys.readouterr().err
    assert not (run / "merged.json").exists()


def test_missing_agreement_entry_is_error(tmp_path):
    run = write_run(tmp_path, [candidate(1, "medium")], {}, [verdict(1)])
    with pytest.raises(merge.MergeError, match="no agreement entry"):
        merge.run(run)


def test_no_verdict_file_without_flag_is_error(tmp_path):
    run = write_run(tmp_path, [candidate(1)], {1: agree("sonnet", "sol")})
    assert merge.main([str(run)]) == 2
