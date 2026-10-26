#!/usr/bin/env python3
"""Apply the review-ensemble merge rules to a run directory.

Reads ``normalized.json``, ``verdicts*.json``, and ``changed_files.txt``
from the run directory; writes ``merged.json``, ``coverage.json``, and
``summary.md``; prints ``summary.md`` to stdout.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SEVERITIES = ("high", "medium", "low")
PRIORITY_CATEGORIES = {"correctness", "security", "reliability"}
VERDICTS = ("keep", "drop")
MAX_ROWS = 10
REQUIRED_CANDIDATE_KEYS = (
    "id",
    "severity",
    "category",
    "file",
    "lines",
    "issue",
    "fix",
)


class MergeError(Exception):
    pass


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise MergeError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise MergeError(f"invalid JSON in {path}: {exc}") from exc


def norm_path(path: str) -> str:
    path = path.strip()
    while path.startswith("./"):
        path = path[2:]
    return path


def load_changed_files(run_dir: Path) -> set[str]:
    path = run_dir / "changed_files.txt"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise MergeError(f"cannot read {path}: {exc}") from exc
    return {norm_path(line) for line in lines if line.strip()}


def load_verdicts(run_dir: Path) -> dict[int, dict[str, Any]]:
    files = sorted(run_dir.glob("verdicts*.json"))
    if not files:
        raise MergeError("no verdicts*.json in run dir (use --no-validator)")
    verdicts: dict[int, dict[str, Any]] = {}
    for path in files:
        data = load_json(path)
        if not isinstance(data, list):
            raise MergeError(f"{path.name} must be a JSON array")
        for item in data:
            if not isinstance(item, dict) or "id" not in item:
                raise MergeError(f"{path.name}: verdict without id")
            vid = item["id"]
            if not isinstance(vid, int):
                raise MergeError(f"{path.name}: verdict id {vid!r} not int")
            if vid in verdicts:
                raise MergeError(f"{path.name}: duplicate verdict id {vid}")
            verdict = item.get("verdict")
            if verdict not in VERDICTS:
                raise MergeError(
                    f"{path.name}: id {vid} has verdict {verdict!r}"
                )
            verdicts[vid] = item
    return verdicts


def validate_candidate(candidate: Any) -> dict[str, Any]:
    if not isinstance(candidate, dict):
        raise MergeError("candidate is not an object")
    for key in REQUIRED_CANDIDATE_KEYS:
        if key not in candidate:
            raise MergeError(f"candidate missing key {key!r}: {candidate}")
    if not isinstance(candidate["id"], int):
        raise MergeError(f"candidate id {candidate['id']!r} not int")
    if candidate["severity"] not in SEVERITIES:
        raise MergeError(
            f"candidate {candidate['id']} has severity "
            f"{candidate['severity']!r}"
        )
    return candidate


def reviewer_names(agreement: Any, cid: int) -> list[str]:
    if not isinstance(agreement, list) or not agreement:
        raise MergeError(f"candidate {cid} has no agreement entry")
    names: list[str] = []
    for entry in agreement:
        if not isinstance(entry, dict) or "reviewer" not in entry:
            raise MergeError(f"candidate {cid}: malformed agreement entry")
        name = str(entry["reviewer"])
        if name not in names:
            names.append(name)
    return names


def is_unchecked(verdict: dict[str, Any] | None) -> bool:
    if verdict is None:
        return True
    reason = verdict.get("reason") or ""
    return str(reason).strip().lower().startswith("unchecked")


def sort_key(row: dict[str, Any]) -> tuple[int, int, int, int]:
    return (
        SEVERITIES.index(row["severity"]),
        0 if row["category"] in PRIORITY_CATEGORIES else 1,
        -len(row["agreed_by"]),
        row["id"],
    )


def merge(
    normalized: dict[str, Any],
    verdicts: dict[int, dict[str, Any]] | None,
    changed_files: set[str],
) -> dict[str, Any]:
    """Apply the merge rules. ``verdicts`` is None in --no-validator mode."""
    candidates = normalized.get("candidates")
    if not isinstance(candidates, list):
        raise MergeError("normalized.json: candidates must be an array")
    agreement_map = normalized.get("agreement")
    if not isinstance(agreement_map, dict):
        raise MergeError("normalized.json: agreement must be an object")

    counts = {
        "duplicates": int(normalized.get("duplicates_merged") or 0),
        "single_low": 0,
        "validator_dropped": 0,
        "unchecked": 0,
        "out_of_diff": 0,
        "text_corrected": 0,
    }
    rows: list[dict[str, Any]] = []

    for raw in candidates:
        cand = validate_candidate(raw)
        cid = cand["id"]
        agreed_by = reviewer_names(agreement_map.get(str(cid)), cid)
        multi = len(agreed_by) >= 2

        if norm_path(str(cand["file"])) not in changed_files:
            counts["out_of_diff"] += 1
            continue

        verdict: dict[str, Any] | None = None
        if verdicts is not None:
            verdict = verdicts.get(cid)
            if verdict is None:
                raise MergeError(f"no verdict for candidate {cid}")
            if verdict["verdict"] == "drop":
                counts["validator_dropped"] += 1
                continue

        severity = cand["severity"]
        finding = str(cand["issue"]).strip()
        corrected = False

        if is_unchecked(verdict):
            if not multi:
                counts["unchecked"] += 1
                continue
        else:
            assert verdict is not None
            if not multi and severity == "low":
                counts["single_low"] += 1
                continue
            corrected_issue = verdict.get("corrected_issue")
            if corrected_issue:
                finding = str(corrected_issue).strip()
                corrected = True
                counts["text_corrected"] += 1
            validator_severity = verdict.get("severity")
            if (
                validator_severity in SEVERITIES
                and validator_severity != severity
            ):
                finding = f"{finding} (reviewers: {severity})"
                severity = validator_severity

        rows.append(
            {
                "id": cid,
                "severity": severity,
                "reviewers_severity": cand["severity"],
                "category": str(cand["category"]),
                "file": norm_path(str(cand["file"])),
                "lines": str(cand["lines"]),
                "finding": finding,
                "corrected": corrected,
                "agreed_by": agreed_by,
                "fix": str(cand["fix"]),
                "fix_source": str(cand.get("fix_source") or "reviewer"),
                "evidence": str(cand.get("evidence") or ""),
            }
        )

    rows.sort(key=sort_key)
    kept = rows[:MAX_ROWS]
    deferred = rows[MAX_ROWS:]
    for number, row in enumerate(kept, start=1):
        row["n"] = number

    counts["omitted"] = (
        counts["duplicates"]
        + counts["single_low"]
        + counts["validator_dropped"]
        + counts["unchecked"]
        + counts["out_of_diff"]
    )

    return {
        "rows": kept,
        "deferred": deferred,
        "verdict": build_verdict(kept),
        "coverage": counts,
    }


def build_verdict(rows: list[dict[str, Any]]) -> dict[str, str]:
    if not rows:
        return {
            "status": "ready",
            "sentence": "No finding survived the panel and the validator.",
        }
    high = [str(r["n"]) for r in rows if r["severity"] == "high"]
    if high:
        return {
            "status": "not ready",
            "sentence": f"Rows {', '.join(high)} are high.",
        }
    numbers = ", ".join(str(r["n"]) for r in rows)
    return {
        "status": "ready with fixes",
        "sentence": f"Rows {numbers} should be fixed before merge.",
    }


def cell(text: str) -> str:
    return " ".join(str(text).split()).replace("|", "\\|")


def render_table(rows: list[dict[str, Any]]) -> str:
    lines = [
        "| # | Sev | Category | Location | Finding | Agreed by |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        location = f"`{row['file']}:{row['lines']}`"
        lines.append(
            f"| {row['n']} | {row['severity']} | {cell(row['category'])} "
            f"| {location} | {cell(row['finding'])} "
            f"| {', '.join(row['agreed_by'])} |"
        )
    return "\n".join(lines)


def render_deferred(deferred: list[dict[str, Any]]) -> str:
    items = [
        f"`{row['file']}:{row['lines']}` - {cell(row['finding'])}"
        for row in deferred
    ]
    return "Deferred: " + "; ".join(items)


def coverage_lines(counts: dict[str, int]) -> list[str]:
    return [
        (
            f"Omitted {counts['omitted']} findings "
            f"({counts['duplicates']} duplicates, "
            f"{counts['single_low']} single-reviewer low, "
            f"{counts['validator_dropped']} validator dropped, "
            f"{counts['unchecked']} unchecked (budget), "
            f"{counts['out_of_diff']} out of diff)."
        ),
        f"Text corrected: {counts['text_corrected']} rows.",
    ]


def render_summary(result: dict[str, Any]) -> str:
    verdict = result["verdict"]
    parts = [
        "### Verdict",
        "",
        f"{verdict['status']}: {verdict['sentence']}",
        "",
        "### Findings",
        "",
    ]
    if result["rows"]:
        parts.append(render_table(result["rows"]))
    else:
        parts.append("No findings.")
    if result["deferred"]:
        parts.extend(["", render_deferred(result["deferred"])])
    parts.extend(["", *coverage_lines(result["coverage"])])
    return "\n".join(parts) + "\n"


def build_coverage(
    normalized: dict[str, Any],
    result: dict[str, Any],
    *,
    no_validator: bool,
) -> dict[str, Any]:
    coverage = dict(result["coverage"])
    coverage["reviewers"] = list(normalized.get("reviewers") or [])
    coverage["budget_reached"] = list(normalized.get("budget_reached") or [])
    coverage["tools"] = str(normalized.get("tools") or "skipped: not run")
    coverage["checked_union"] = str(normalized.get("checked_union") or "")
    coverage["declined_shared"] = list(normalized.get("declined_shared") or [])
    coverage["validator"] = "none (--no-validator)" if no_validator else "ran"
    return coverage


def run(run_dir: Path, *, no_validator: bool = False) -> dict[str, Any]:
    normalized = load_json(run_dir / "normalized.json")
    if not isinstance(normalized, dict):
        raise MergeError("normalized.json must be an object")
    verdicts = None if no_validator else load_verdicts(run_dir)
    changed_files = load_changed_files(run_dir)

    result = merge(normalized, verdicts, changed_files)
    coverage = build_coverage(normalized, result, no_validator=no_validator)
    summary = render_summary(result)

    (run_dir / "merged.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    (run_dir / "coverage.json").write_text(
        json.dumps(coverage, indent=2) + "\n", encoding="utf-8"
    )
    (run_dir / "summary.md").write_text(summary, encoding="utf-8")
    return {"result": result, "coverage": coverage, "summary": summary}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", help="Run directory written by the skill")
    parser.add_argument(
        "--no-validator",
        action="store_true",
        help="No verdicts available: treat every candidate as unchecked",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        out = run(Path(args.run_dir), no_validator=args.no_validator)
    except MergeError as exc:
        sys.stderr.write(f"merge_error: {exc}\n")
        return 2
    sys.stdout.write(out["summary"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
