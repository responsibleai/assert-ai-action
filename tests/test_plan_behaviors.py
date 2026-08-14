import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[1]
_MODULE_PATH = _ROOT / "scripts" / "plan_behaviors.py"
_SPEC = importlib.util.spec_from_file_location("plan_behaviors", _MODULE_PATH)
assert _SPEC is not None
plan_behaviors = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(plan_behaviors)


def _write_config(path: Path, suite: str, behavior: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "suite": suite,
                "run": "baseline",
                "behavior": {"name": behavior, "description": "..."},
                "pipeline": {"inference": {"target": {"callable": "agent.agent:chat"}}},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def _write_scores(directory: Path, rows: dict[str, dict[str, bool]]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "scores.jsonl").open("w", encoding="utf-8") as fh:
        for tc_id, dims in rows.items():
            fh.write(json.dumps({"test_case_id": tc_id, "verdict": {"dimensions": dims}}) + "\n")


def test_glob_expands_to_one_behavior_per_config(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path / "eval" / "behaviors" / "leakage.yaml", "bank-leakage", "leakage")
    _write_config(tmp_path / "eval" / "behaviors" / "txn.yaml", "bank-txn", "transactions")

    rc = plan_behaviors.main(
        [
            "plan",
            "--configs",
            "eval/behaviors/*.yaml",
            "--artifacts-root",
            str(tmp_path / "arts"),
            "--out",
            "manifest.json",
        ]
    )

    assert rc == 0
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert [e["name"] for e in manifest] == ["leakage", "transactions"]
    # Each behavior gets its own artifacts_root, otherwise the second run would
    # overwrite the first and the gate would silently compare a suite to itself.
    roots = {e["artifacts_root"] for e in manifest}
    assert len(roots) == 2
    for entry in manifest:
        frozen = yaml.safe_load(Path(entry["frozen"]).read_text(encoding="utf-8"))
        assert frozen["artifacts_root"] == entry["artifacts_root"].replace("/", os.sep) or frozen[
            "artifacts_root"
        ].replace(os.sep, "/") == entry["artifacts_root"]


def test_newline_list_and_explicit_paths_also_expand(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    a = _write_config(tmp_path / "a.yaml", "suite-a", "alpha")
    b = _write_config(tmp_path / "b.yaml", "suite-b", "beta")

    rc = plan_behaviors.main(
        [
            "plan",
            "--configs",
            f"{a.name}\n{b.name}\n",
            "--artifacts-root",
            str(tmp_path / "arts"),
            "--out",
            "manifest.json",
        ]
    )

    assert rc == 0
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert [e["name"] for e in manifest] == ["alpha", "beta"]


def test_no_match_is_an_error(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    rc = plan_behaviors.main(
        [
            "plan",
            "--configs",
            "eval/behaviors/*.yaml",
            "--artifacts-root",
            str(tmp_path / "arts"),
            "--out",
            "manifest.json",
        ]
    )
    assert rc == 1


def test_resolve_pairs_each_behavior_with_its_own_baseline(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path / "eval" / "behaviors" / "leakage.yaml", "bank-leakage", "leakage")
    _write_config(tmp_path / "eval" / "behaviors" / "txn.yaml", "bank-txn", "transactions")
    plan_behaviors.main(
        [
            "plan",
            "--configs",
            "eval/behaviors/*.yaml",
            "--artifacts-root",
            str(tmp_path / "arts"),
            "--out",
            "manifest.json",
        ]
    )
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))

    good = {f"case-{i}": {"policy_violation": i < 5} for i in range(40)}
    for entry in manifest:
        _write_scores(Path(entry["artifacts_root"]) / "results" / entry["suite"] / "run1", good)

    bad = {f"case-{i}": {"policy_violation": i < 30} for i in range(40)}
    for suite in ("bank-leakage", "bank-txn"):
        _write_scores(tmp_path / "base" / "results" / suite / "run0", bad)

    rc = plan_behaviors.main(
        [
            "resolve",
            "--manifest",
            "manifest.json",
            "--baseline-root",
            str(tmp_path / "base"),
            "--out",
            "comparable.json",
        ]
    )

    assert rc == 0
    comparable = json.loads((tmp_path / "comparable.json").read_text(encoding="utf-8"))
    assert len(comparable) == 2
    # The critical property: each behavior's baseline must come from its OWN
    # suite directory, not whichever run happened to sort last.
    for entry in comparable:
        suite = "bank-leakage" if entry["name"] == "leakage" else "bank-txn"
        assert suite in entry["baseline"]
        assert suite in entry["current"]


def test_resolve_reports_no_baseline_without_failing(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path / "eval" / "behaviors" / "leakage.yaml", "bank-leakage", "leakage")
    plan_behaviors.main(
        [
            "plan",
            "--configs",
            "eval/behaviors/*.yaml",
            "--artifacts-root",
            str(tmp_path / "arts"),
            "--out",
            "manifest.json",
        ]
    )
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    _write_scores(
        Path(manifest[0]["artifacts_root"]) / "results" / "bank-leakage" / "run1",
        {"case-0": {"policy_violation": False}},
    )

    rc = plan_behaviors.main(
        [
            "resolve",
            "--manifest",
            "manifest.json",
            "--baseline-root",
            "",
            "--out",
            "comparable.json",
            "--all-out",
            "resolved.json",
        ]
    )

    assert rc == 0
    assert json.loads((tmp_path / "comparable.json").read_text(encoding="utf-8")) == []
    resolved = json.loads((tmp_path / "resolved.json").read_text(encoding="utf-8"))
    assert resolved[0]["baseline"] is None


def test_resolve_emits_dropped_behavior_count_and_names(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    output = tmp_path / "github-output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    _write_config(tmp_path / "eval" / "behaviors" / "with.yaml", "with-baseline", "with baseline")
    _write_config(tmp_path / "eval" / "behaviors" / "without.yaml", "without-baseline", "without baseline")
    plan_behaviors.main(
        [
            "plan",
            "--configs",
            "eval/behaviors/*.yaml",
            "--artifacts-root",
            str(tmp_path / "arts"),
            "--out",
            "manifest.json",
        ]
    )
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    for entry in manifest:
        _write_scores(Path(entry["artifacts_root"]) / "results" / entry["suite"] / "run1", {"case-0": {"policy_violation": False}})
    _write_scores(tmp_path / "base" / "results" / "with-baseline" / "run0", {"case-0": {"policy_violation": False}})

    rc = plan_behaviors.main(
        [
            "resolve",
            "--manifest",
            "manifest.json",
            "--baseline-root",
            str(tmp_path / "base"),
            "--out",
            "comparable.json",
        ]
    )

    assert rc == 0
    comparable = json.loads((tmp_path / "comparable.json").read_text(encoding="utf-8"))
    assert [entry["name"] for entry in comparable] == ["with baseline"]
    emitted = output.read_text(encoding="utf-8")
    assert "dropped-count=1" in emitted
    assert "dropped-names=without baseline" in emitted


def test_resolve_errors_when_two_behaviors_share_one_baseline_run(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path / "eval" / "behaviors" / "a.yaml", "shared-suite", "alpha")
    _write_config(tmp_path / "eval" / "behaviors" / "b.yaml", "shared-suite", "beta")
    plan_behaviors.main(
        [
            "plan",
            "--configs",
            "eval/behaviors/*.yaml",
            "--artifacts-root",
            str(tmp_path / "arts"),
            "--out",
            "manifest.json",
        ]
    )
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    for entry in manifest:
        _write_scores(Path(entry["artifacts_root"]) / "results" / entry["suite"] / "run1", {"case-0": {"policy_violation": False}})
    _write_scores(tmp_path / "base" / "results" / "shared-suite" / "run0", {"case-0": {"policy_violation": False}})

    rc = plan_behaviors.main(
        [
            "resolve",
            "--manifest",
            "manifest.json",
            "--baseline-root",
            str(tmp_path / "base"),
            "--out",
            "comparable.json",
        ]
    )

    assert rc == 1
    assert "multiple behaviors resolved to the same baseline run" in capsys.readouterr().err


def test_plan_then_resolve_then_compare_runs_end_to_end(tmp_path, monkeypatch) -> None:
    """The full multi-behavior chain the action wires together."""
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path / "eval" / "behaviors" / "leakage.yaml", "bank-leakage", "leakage")
    _write_config(tmp_path / "eval" / "behaviors" / "txn.yaml", "bank-txn", "transactions")
    plan_behaviors.main(
        [
            "plan",
            "--configs",
            "eval/behaviors/*.yaml",
            "--artifacts-root",
            str(tmp_path / "arts"),
            "--out",
            "manifest.json",
        ]
    )
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))

    fixed = {f"case-{i}": {"policy_violation": i < 5, "overrefusal": False} for i in range(40)}
    broken = {f"case-{i}": {"policy_violation": i < 30, "overrefusal": False} for i in range(40)}
    for entry in manifest:
        _write_scores(Path(entry["artifacts_root"]) / "results" / entry["suite"] / "run1", fixed)
        _write_scores(tmp_path / "base" / "results" / entry["suite"] / "run0", broken)

    plan_behaviors.main(
        [
            "resolve",
            "--manifest",
            "manifest.json",
            "--baseline-root",
            str(tmp_path / "base"),
            "--out",
            "comparable.json",
        ]
    )

    result = subprocess.run(
        [
            sys.executable,
            str(_ROOT / "scripts" / "compare_runs.py"),
            "--behaviors",
            "comparable.json",
            "--gate-mode",
            "improvement",
            "--out",
            "gate_report.json",
            "--pr-comment",
            "pr_comment.md",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    report = json.loads((tmp_path / "gate_report.json").read_text(encoding="utf-8"))
    assert report["gate_mode"] == "improvement"
    assert report["behaviors_evaluated"] == 2
    assert report["family_size"] == 4
    assert report["decision"] == "PASS"
    body = (tmp_path / "pr_comment.md").read_text(encoding="utf-8")
    assert "| Behavior | Dimension |" in body


def _write_nested_run(directory: Path, generation: str = "20260814T095043") -> None:
    """Write a current-layout run tree: eval-XXX/ has test_set.jsonl and suite.json;
    the per-generation subdir eval-XXX/YYY/ has scores.jsonl.

    Reproduces the layout produced by recent `assert-ai` versions and
    exercises the code path that anchors on `suite.json` at the outer level.
    """
    inner = directory / generation
    inner.mkdir(parents=True, exist_ok=True)
    (directory / "suite.json").write_text("{}\n", encoding="utf-8")
    (directory / "test_set.jsonl").write_text(
        '{"test_case_id": "case-0", "prompt": "..."}\n', encoding="utf-8"
    )
    (inner / "scores.jsonl").write_text(
        '{"test_case_id": "case-0", "verdict": {"dimensions": {"policy_violation": false}}}\n',
        encoding="utf-8",
    )
    (inner / "config.yaml").write_text("run: baseline\n", encoding="utf-8")


def test_resolve_returns_outer_run_dir_for_nested_layouts(tmp_path, monkeypatch) -> None:
    """Regression: `test_set.jsonl` lives at the eval-<ts>/ level, but
    `scores.jsonl` lives one level down. Anchoring `_find_run_dir` on
    `scores.jsonl` returned the inner dir and silently disabled the paired
    gate — `detect_test_set_drift.py` `rglob`d from the inner dir and never
    found `test_set.jsonl`, so every PR reported FirstRun. Anchor on
    `suite.json` (which lives at the outer level) instead.
    """
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path / "eval" / "behaviors" / "leakage.yaml", "bank-leakage", "leakage")
    plan_behaviors.main(
        [
            "plan",
            "--configs",
            "eval/behaviors/*.yaml",
            "--artifacts-root",
            str(tmp_path / "arts"),
            "--out",
            "manifest.json",
        ]
    )
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    current_root = Path(manifest[0]["artifacts_root"]) / "results" / "eval-20260814T100915"
    baseline_root = tmp_path / "base" / "results" / "eval-20260814T095043"
    _write_nested_run(current_root, generation="20260814T100915")
    _write_nested_run(baseline_root, generation="20260814T095043")

    rc = plan_behaviors.main(
        [
            "resolve",
            "--manifest",
            "manifest.json",
            "--baseline-root",
            str(tmp_path / "base"),
            "--out",
            "comparable.json",
            "--all-out",
            "resolved.json",
        ]
    )
    assert rc == 0
    resolved = json.loads((tmp_path / "resolved.json").read_text(encoding="utf-8"))
    assert len(resolved) == 1
    entry = resolved[0]
    # The critical property: the resolved paths must point at the OUTER
    # eval-<ts>/ dir where suite.json lives, not the inner generation dir,
    # so downstream rglob can still find test_set.jsonl.
    for role in ("current", "baseline"):
        assert (Path(entry[role]) / "test_set.jsonl").is_file(), (
            f"{role} run root {entry[role]!r} is missing test_set.jsonl -- "
            f"_find_run_dir picked the inner generation dir instead of the outer eval dir"
        )
        assert (Path(entry[role]) / "suite.json").is_file()


def test_plan_pins_suite_to_slug_when_config_omits_it(tmp_path, monkeypatch) -> None:
    """Regression: when a behavior config has no `suite:`, `assert-ai` defaults
    `suite_id` to `eval-<timestamp>` and every dispatch writes into a fresh
    `results/<eval-XXX>/`. The cache lookup never crosses dispatches, so the
    paired McNemar gate re-generates the test_set every run and drift always
    fires. Pin `suite` to the behavior slug so consecutive runs share one
    `results/<slug>/` and the artifact cache can actually reuse the frozen
    test_set from the baseline dispatch.
    """
    monkeypatch.chdir(tmp_path)
    # No `suite:` in this fixture; matches the shape of banking/foundry demos.
    (tmp_path / "eval" / "behaviors").mkdir(parents=True)
    (tmp_path / "eval" / "behaviors" / "leakage.yaml").write_text(
        yaml.safe_dump(
            {
                "behavior": {"name": "leakage", "description": "..."},
                "pipeline": {"inference": {"target": {"callable": "agent:chat"}}},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    rc = plan_behaviors.main(
        [
            "plan",
            "--configs",
            "eval/behaviors/*.yaml",
            "--artifacts-root",
            str(tmp_path / "arts"),
            "--out",
            "manifest.json",
        ]
    )
    assert rc == 0

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest[0]["suite"] == manifest[0]["slug"]

    frozen = yaml.safe_load(Path(manifest[0]["frozen"]).read_text(encoding="utf-8"))
    assert frozen["suite"] == manifest[0]["slug"], (
        "the frozen config must carry the pinned suite so `assert-ai run` picks "
        "it up as its suite_id instead of defaulting to eval-<timestamp>"
    )


def test_plan_preserves_user_supplied_suite(tmp_path, monkeypatch) -> None:
    """A user who already set `suite:` in their config keeps their own layout;
    we only default to the slug when the field is unset.
    """
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path / "eval" / "behaviors" / "leakage.yaml", "custom-suite-id", "leakage")

    rc = plan_behaviors.main(
        [
            "plan",
            "--configs",
            "eval/behaviors/*.yaml",
            "--artifacts-root",
            str(tmp_path / "arts"),
            "--out",
            "manifest.json",
        ]
    )
    assert rc == 0

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest[0]["suite"] == "custom-suite-id"
    frozen = yaml.safe_load(Path(manifest[0]["frozen"]).read_text(encoding="utf-8"))
    assert frozen["suite"] == "custom-suite-id"
