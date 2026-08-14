#!/usr/bin/env python3
"""Detect baseline-vs-current test-set drift before running the paired gate.

When the test set changes (judged via SHA-256 of ``test_set.jsonl``), the
paired comparison is skipped because pairing is no longer valid. This script:

1. Emits a ``TestSetChanged`` gate report and PR comment.
2. Signals ``action.yml`` via ``GITHUB_OUTPUT`` to skip the comparator
   (``skip-compare=true``, ``gate-verdict=TestSetChanged``).

When SHAs match, the script just emits the SHAs and lets ``action.yml`` run
the comparator (``skip-compare=false``).

If the baseline lacks ``test_set.jsonl`` entirely, emits a ``FirstRun`` report
to match the no-baseline path in ``action.yml``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

try:
    from _version import ACTION_VERSION
except ImportError:  # invoked as a module rather than a script
    from scripts._version import ACTION_VERSION


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


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _current_stats(root: Path) -> tuple[int, float]:
    scores = _find_file(root, "scores.jsonl")
    rows: list[dict] = []
    if scores and scores.is_file():
        for line in scores.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    violations = 0
    for row in rows:
        dims = ((row.get("verdict") or {}).get("dimensions") or {})
        if any(value is True for value in dims.values()):
            violations += 1
    return len(rows), violations / len(rows) if rows else 0.0


def _current_stats_many(roots: list[Path]) -> tuple[int, float]:
    total = 0
    weighted_violations = 0.0
    for root in roots:
        n_cases, violation_rate = _current_stats(root)
        total += n_cases
        weighted_violations += n_cases * violation_rate
    return total, (weighted_violations / total) if total else 0.0


def _emit(**values: str) -> None:
    """Append ``key=value`` lines to ``$GITHUB_OUTPUT``; no-op locally."""
    output = os.environ.get("GITHUB_OUTPUT")
    if not output:
        return
    with open(output, "a", encoding="utf-8") as f:
        for key, value in values.items():
            print(f"{key}={value}", file=f)


def _write_firstrun(args: argparse.Namespace) -> int:
    pairs = _load_pairs(args)
    current_root = Path(pairs[0]["current"]) if pairs else args.current_run_root
    n_cases, violation_rate = _current_stats(current_root) if current_root else (0, 0.0)
    report = {
        "action_version": ACTION_VERSION,
        "decision": "FirstRun",
        "n_paired_cases": 0,
        "current_n_cases": n_cases,
        "current_violation_rate": violation_rate,
        "warnings": ["baseline is missing test_set.jsonl"],
        "dimensions": [],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    args.pr_comment.parent.mkdir(parents=True, exist_ok=True)
    args.pr_comment.write_text(
        "## 🛡️ ASSERT — safety regression gate\n\n"
        "**Gate: 🆕 FirstRun**\n\n"
        "🆕 First run on this branch — no usable baseline test set was found. "
        "Once this merges, future PRs will pair-test against it.\n",
        encoding="utf-8",
    )
    _emit(**{"skip-compare": "true", "gate-verdict": "FirstRun"})
    return 0


def _write_test_set_changed(
    args: argparse.Namespace,
    drifted: list[dict[str, str]],
) -> int:
    roots = [Path(entry["current"]) for entry in _load_pairs(args)]
    n_cases, violation_rate = _current_stats_many(roots)
    drifted_names = [d["name"] for d in drifted]
    report = {
        "action_version": ACTION_VERSION,
        "decision": "TestSetChanged",
        "n_paired_cases": 0,
        "current_n_cases": n_cases,
        "current_violation_rate": violation_rate,
        "drifted_behaviors": drifted_names,
        "test_set_drift": drifted,
        "warnings": [
            "test_set.jsonl changed for behavior(s): "
            + ", ".join(drifted_names)
            + "; paired comparison skipped"
        ],
        "dimensions": [],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    args.pr_comment.parent.mkdir(parents=True, exist_ok=True)
    args.pr_comment.write_text(
        "## 🛡️ ASSERT — safety regression gate\n\n"
        "**Gate: 🔄 TestSetChanged**\n\n"
        "🔄 Test set changed for behavior(s): "
        + ", ".join(f"`{name}`" for name in drifted_names)
        + " — paired comparison skipped. This is a baseline-refresh PR; merge to make it the new baseline.\n",
        encoding="utf-8",
    )
    _emit(**{
        "skip-compare": "true",
        "gate-verdict": "TestSetChanged",
        "drifted-behaviors": ",".join(drifted_names),
    })
    return 0


def _load_pairs(args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.behaviors:
        return json.loads(args.behaviors.read_text(encoding="utf-8"))
    return [
        {
            "name": "default",
            "baseline": str(args.baseline_root),
            "current": str(args.current_run_root),
        }
    ]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--behaviors",
        type=Path,
        default=None,
        help="JSON list of per-behavior {name, baseline, current} pairs from plan_behaviors.py resolve.",
    )
    p.add_argument("--baseline-root", type=Path)
    p.add_argument("--current-run-root", type=Path)
    p.add_argument(
        "--artifacts-root",
        required=True,
        type=Path,
        help="Workspace artifacts root; searched as a fallback for test_set.jsonl when current-run-root has none.",
    )
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--pr-comment", required=True, type=Path)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    pairs = _load_pairs(args)
    if not pairs:
        return _write_firstrun(args)

    drifted: list[dict[str, str]] = []
    baseline_missing: list[str] = []
    matching_shas: list[str] = []
    for pair in pairs:
        name = str(pair.get("name") or pair.get("config") or "behavior")
        baseline_root = Path(pair["baseline"])
        current_root = Path(pair["current"])
        baseline_test = _find_file(baseline_root, "test_set.jsonl")
        current_test = _find_file(current_root, "test_set.jsonl")
        if current_test is None and not args.behaviors:
            current_test = _find_file(args.artifacts_root, "test_set.jsonl")

        if baseline_test is None:
            baseline_missing.append(name)
            continue

        if current_test is None:
            print(
                f"::error::current run for behavior {name!r} did not produce test_set.jsonl; cannot validate paired cases",
                file=sys.stderr,
            )
            return 1

        baseline_sha = _sha256(baseline_test)
        current_sha = _sha256(current_test)
        if baseline_sha != current_sha:
            drifted.append(
                {
                    "name": name,
                    "baseline_test_set_sha256": baseline_sha,
                    "current_test_set_sha256": current_sha,
                    "baseline_test_set_path": str(baseline_test),
                    "current_test_set_path": str(current_test),
                }
            )
        else:
            matching_shas.append(current_sha)

    if baseline_missing:
        return _write_firstrun(args)

    if not drifted:
        sha = matching_shas[0] if matching_shas else ""
        _emit(**{
            "skip-compare": "false",
            "gate-verdict": "",
            "baseline-test-set-sha": sha,
            "current-test-set-sha": sha,
        })
        return 0

    return _write_test_set_changed(args, drifted)


if __name__ == "__main__":
    sys.exit(main())
