#!/usr/bin/env python3
"""Expand, freeze, and resolve the set of ASSERT behavior configs a gate runs.

ASSERT configs are written one behavior per YAML, so the action accepts a glob
or a newline-delimited list rather than a single path. This script owns the two
bookkeeping steps around that:

``plan``
    Expand ``--configs`` into concrete files, give each one its own
    ``artifacts_root`` so runs never collide, write the frozen copies the CLI
    will actually execute, and emit a manifest.

``resolve``
    After the runs complete, locate each behavior's current run directory and
    its matching baseline run directory, and emit the ``behaviors.json`` that
    ``compare_runs.py --behaviors`` consumes.

Keeping this out of ``action.yml`` means it is unit-testable and debuggable
locally, which inline shell-embedded Python is not.
"""
from __future__ import annotations

import argparse
import glob as globlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import yaml

FROZEN_DIR = ".assert-ai-ci"


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-")
    return slug or "behavior"


def _expand_configs(raw: str) -> list[Path]:
    """Expand a newline-delimited list and/or glob patterns into config paths.

    Both forms are accepted because a user hand-writing a workflow reaches for a
    glob, while a coding agent generating one tends to emit an explicit list.
    """
    seen: list[Path] = []
    for chunk in raw.replace(",", "\n").splitlines():
        pattern = chunk.strip()
        if not pattern:
            continue
        matches = sorted(globlib.glob(pattern, recursive=True))
        candidates = [Path(m) for m in matches] if matches else [Path(pattern)]
        for candidate in candidates:
            if candidate.is_file() and candidate not in seen:
                seen.append(candidate)
    return seen


def _behavior_name(cfg: dict[str, Any], config_path: Path) -> str:
    behavior = cfg.get("behavior")
    if isinstance(behavior, dict) and behavior.get("name"):
        return str(behavior["name"])
    if cfg.get("suite"):
        return str(cfg["suite"])
    return config_path.stem


def plan(args: argparse.Namespace) -> int:
    configs = _expand_configs(args.configs)
    if not configs:
        sys.stderr.write(f"::error::no eval configs matched: {args.configs!r}\n")
        return 1

    artifacts_base = Path(args.artifacts_root).resolve()
    frozen_dir = Path(FROZEN_DIR)
    frozen_dir.mkdir(parents=True, exist_ok=True)

    behaviors: list[dict[str, Any]] = []
    used_slugs: set[str] = set()
    for config_path in configs:
        with config_path.open("r", encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}

        name = _behavior_name(cfg, config_path)
        slug = _slugify(cfg.get("suite") or name)
        # Two behaviors may legitimately share a suite name; keep roots distinct.
        if slug in used_slugs:
            slug = _slugify(f"{slug}-{config_path.stem}")
        used_slugs.add(slug)

        artifacts_root = artifacts_base / slug
        cfg["artifacts_root"] = str(artifacts_root)
        # Pin the suite_id so every dispatch of the same behavior writes into
        # the same `results/<suite>/` directory. Without this, `assert-ai`
        # defaults `suite_id` to `eval-<current-timestamp>` on every run, so
        # the previous run's cached test_set / inference / judge artifacts
        # live at a path the current run never looks at. The paired McNemar
        # gate then re-generates the test_set from scratch, the drift
        # detector correctly reports `TestSetChanged`, and no-code-change PRs
        # can never reach PASS.
        #
        # Respect a user-supplied `suite:` when present so anyone already
        # relying on their own suite naming keeps that layout; only default
        # to the slug when the config left it unset.
        suite = cfg.get("suite") or slug
        cfg["suite"] = suite

        frozen = frozen_dir / f"{slug}.yaml"
        with frozen.open("w", encoding="utf-8") as fh:
            yaml.safe_dump(cfg, fh, sort_keys=False)

        behaviors.append(
            {
                "name": name,
                "slug": slug,
                "suite": suite,
                "config": str(config_path).replace(os.sep, "/"),
                "frozen": str(frozen).replace(os.sep, "/"),
                "artifacts_root": str(artifacts_root).replace(os.sep, "/"),
            }
        )

    Path(args.out).write_text(json.dumps(behaviors, indent=2), encoding="utf-8")
    _emit(count=str(len(behaviors)), manifest=str(args.out))
    for entry in behaviors:
        print(f"[plan] {entry['name']} -> {entry['frozen']}")
    return 0


def _find_run_dir(
    root: Path, *, prefer: str | None = None, require_prefer_match: bool = False
) -> Path | None:
    """Return the run directory holding a complete evaluation under ``root``.

    Anchors on ``suite.json`` first because current ``assert-ai`` layouts nest
    a per-generation subdirectory under each ``eval-<timestamp>/`` run root::

        eval-XXX/                  # ← run root: suite.json, test_set.jsonl live here
        eval-XXX/YYY/scores.jsonl  # ← per-generation subdir

    An earlier version anchored on ``scores.jsonl``, which returned the inner
    generation subdirectory. Downstream consumers then called
    ``rglob('test_set.jsonl')`` from that inner dir and found nothing (rglob
    only descends), which quietly disabled the paired gate: every PR reported
    ``FirstRun`` with a "baseline is missing test_set.jsonl" warning even
    though the baseline was present a level up.

    Falls back to ``scores.jsonl`` for legacy flat layouts where scores lived
    directly under the run root; that path is what all pre-suite.json test
    fixtures still exercise.

    When several run directories exist, prefer one whose path mentions
    ``prefer`` (the suite name) so multi-behavior baselines pair with the
    right behavior instead of silently comparing against whichever run
    sorted first.
    """
    if not root or not root.exists():
        return None
    candidates = sorted(p.parent for p in root.rglob("suite.json") if p.is_file())
    if not candidates:
        candidates = sorted(p.parent for p in root.rglob("scores.jsonl") if p.is_file())
    if not candidates:
        return None
    if prefer:
        wanted = _slugify(prefer).lower()
        matched = [c for c in candidates if wanted in _slugify(str(c)).lower()]
        if matched:
            return matched[-1]
        if require_prefer_match:
            return None
    return candidates[-1]


def resolve(args: argparse.Namespace) -> int:
    behaviors = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    baseline_root = Path(args.baseline_root) if args.baseline_root else None
    single = len(behaviors) == 1

    resolved: list[dict[str, Any]] = []
    missing_current: list[str] = []
    missing_baseline: list[str] = []
    baseline_owners: dict[str, str] = {}
    duplicate_baselines: list[tuple[str, str, str]] = []

    for entry in behaviors:
        suite = entry.get("suite") or entry.get("name")
        current = _find_run_dir(Path(entry["artifacts_root"]), prefer=suite)
        if current is None:
            missing_current.append(entry["name"])
            continue

        baseline = None
        if baseline_root is not None:
            baseline = _find_run_dir(
                baseline_root,
                prefer=None if single else suite,
                require_prefer_match=not single,
            )
        if baseline is None:
            missing_baseline.append(entry["name"])
        else:
            baseline_key = str(baseline.resolve())
            if baseline_key in baseline_owners:
                duplicate_baselines.append((entry["name"], baseline_owners[baseline_key], str(baseline)))
            else:
                baseline_owners[baseline_key] = entry["name"]

        resolved.append(
            {
                "name": entry["name"],
                "config": entry.get("config"),
                "current": str(current).replace(os.sep, "/"),
                "baseline": str(baseline).replace(os.sep, "/") if baseline else None,
            }
        )

    if missing_current:
        sys.stderr.write(
            "::error::no scores.jsonl produced for: " + ", ".join(missing_current) + "\n"
        )
        return 1

    if duplicate_baselines:
        details = "; ".join(
            f"{name} and {owner} both resolved to {baseline}"
            for name, owner, baseline in duplicate_baselines
        )
        sys.stderr.write(
            "::error::multiple behaviors resolved to the same baseline run: "
            + details
            + "\n"
        )
        return 1

    comparable = [r for r in resolved if r["baseline"]]
    Path(args.out).write_text(json.dumps(comparable, indent=2), encoding="utf-8")
    if args.all_out:
        Path(args.all_out).write_text(json.dumps(resolved, indent=2), encoding="utf-8")

    _emit(
        comparable=str(len(comparable)),
        total=str(len(resolved)),
        baseline_available="true" if comparable else "false",
        first_current=resolved[0]["current"] if resolved else "",
        dropped_count=str(len(missing_baseline)),
        dropped_names=",".join(missing_baseline),
    )
    for name in missing_baseline:
        print(f"[resolve] no baseline for behavior: {name}")
    return 0


def _emit(**values: str) -> None:
    output = os.environ.get("GITHUB_OUTPUT")
    if not output:
        return
    with open(output, "a", encoding="utf-8") as fh:
        for key, value in values.items():
            fh.write(f"{key.replace('_', '-')}={value}\n")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="mode", required=True)

    plan_p = sub.add_parser("plan", help="Expand and freeze configs.")
    plan_p.add_argument("--configs", required=True)
    plan_p.add_argument("--artifacts-root", required=True)
    plan_p.add_argument("--out", required=True, type=Path)
    plan_p.set_defaults(func=plan)

    res_p = sub.add_parser("resolve", help="Locate current and baseline run dirs.")
    res_p.add_argument("--manifest", required=True, type=Path)
    res_p.add_argument("--baseline-root", default="")
    res_p.add_argument("--out", required=True, type=Path)
    res_p.add_argument("--all-out", type=Path, default=None)
    res_p.set_defaults(func=resolve)

    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
