#!/usr/bin/env python3
"""Write a FirstRun gate report and PR comment body.

Used by ``action.yml`` when no baseline is available — the current run becomes
the seed baseline once it merges. Emits a structured JSON report and a markdown
PR comment body, both matching the layout the gate's PR commenter expects.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ACTION_VERSION = "v1.0.0-rc1"


def _find_file(root: Path, name: str) -> Path | None:
    if not root.exists():
        return None
    direct = root / name
    if direct.is_file():
        return direct
    # Prefer the lexicographically LAST match: assert-ai names per-generation
    # subdirectories with an ISO-8601 timestamp (`YYYYMMDDTHHMMSS`) so sorting
    # by name is chronological. When the warm-cache step has copied the
    # baseline's per-generation output into the current run's tree, the newer
    # dir is the one produced by *this* run and is what we want.
    matches = sorted(p for p in root.rglob(name) if p.is_file())
    return matches[-1] if matches else None


def _current_stats(root: Path) -> tuple[int, float]:
    """Return ``(n_cases, violation_rate)`` from ``scores.jsonl`` under ``root``.

    Falls back to counting rows in ``test_set.jsonl`` when ``scores.jsonl`` is
    missing or empty (the FirstRun report should still say *something* about the
    test set even if scoring failed).
    """
    scores = _find_file(root, "scores.jsonl")
    rows: list[dict] = []
    if scores and scores.is_file():
        for line in scores.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    if not rows:
        test_set = _find_file(root, "test_set.jsonl")
        if test_set and test_set.is_file():
            n = sum(1 for line in test_set.read_text(encoding="utf-8").splitlines() if line.strip())
            return n, 0.0
        return 0, 0.0
    violations = 0
    for row in rows:
        dims = ((row.get("verdict") or {}).get("dimensions") or {})
        if any(value is True for value in dims.values()):
            violations += 1
    return len(rows), violations / len(rows)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--current-run-root", required=True, type=Path)
    p.add_argument("--baseline-reason", default="no baseline to compare against")
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--pr-comment", required=True, type=Path)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    n_cases, violation_rate = _current_stats(args.current_run_root)
    report = {
        "action_version": ACTION_VERSION,
        "decision": "FirstRun",
        "n_paired_cases": 0,
        "current_n_cases": n_cases,
        "current_violation_rate": violation_rate,
        "warnings": [args.baseline_reason],
        "dimensions": [],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    args.pr_comment.parent.mkdir(parents=True, exist_ok=True)
    args.pr_comment.write_text(
        "## 🛡️ ASSERT — safety regression gate\n\n"
        "**Gate: 🆕 FirstRun**\n\n"
        f"🆕 First run on this branch — no baseline to compare. The current run is "
        f"`{n_cases}` test cases, `{violation_rate:.1%}` overall violation rate. "
        "Once this merges, future PRs will pair-test against it.\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
