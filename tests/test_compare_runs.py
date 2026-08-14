import importlib.util
import json
from itertools import count
from pathlib import Path


_MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "compare_runs.py"
_SPEC = importlib.util.spec_from_file_location("compare_runs", _MODULE_PATH)
assert _SPEC is not None
compare_runs = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(compare_runs)


def test_holm_bonferroni_stops_after_first_miss() -> None:
    # The first ordered p-value misses alpha / 2, so true Holm step-down rejects
    # neither hypothesis. Checking each rank independently would wrongly reject
    # the second p-value against alpha / 1.
    assert compare_runs._holm_bonferroni_rejections([0.03, 0.04], 0.05) == [
        (0.025, False),
        (0.05, False),
    ]


def test_holm_bonferroni_continues_until_first_miss() -> None:
    assert compare_runs._holm_bonferroni_rejections([0.01, 0.03, 0.04], 0.05) == [
        (0.05 / 3, True),
        (0.05 / 2, False),
        (0.05, False),
    ]


def test_verdict_uses_holm_rejection_not_independent_threshold() -> None:
    # This is the customer-visible failure mode: a later dimension must stay
    # inconclusive if an earlier ordered p-value already stopped Holm step-down.
    entries = []
    for p_value, delta_pp in [(0.03, 1.0), (0.04, 2.0)]:
        entries.append({"p_value": p_value, "delta_pp": delta_pp, "n_pairs": 30})

    for entry, (threshold, rejected) in zip(
        entries,
        compare_runs._holm_bonferroni_rejections([e["p_value"] for e in entries], 0.05),
    ):
        entry["alpha_corrected"] = threshold
        entry["holm_rejected"] = rejected
        entry["verdict"] = compare_runs._verdict_for(
            delta_pp=entry["delta_pp"],
            rejected=rejected,
            n_pairs=entry["n_pairs"],
            min_pairs=30,
            allow_inconclusive=True,
        )

    assert [entry["holm_rejected"] for entry in entries] == [False, False]
    assert [entry["verdict"] for entry in entries] == ["Inconclusive", "Inconclusive"]
    assert compare_runs._overall_decision(entries) == "Inconclusive"


def test_compare_applies_holm_stepdown_to_dimension_verdicts(tmp_path, monkeypatch) -> None:
    baseline = tmp_path / "baseline"
    current = tmp_path / "current"
    baseline.mkdir()
    current.mkdir()
    (baseline / "scores.jsonl").write_text("{}\n", encoding="utf-8")
    (current / "scores.jsonl").write_text("{}\n", encoding="utf-8")

    score_rows = {
        "baseline": {
            f"case-{i}": {"dim_a": False, "dim_b": False}
            for i in range(30)
        },
        "current": {
            f"case-{i}": {"dim_a": True, "dim_b": True}
            for i in range(30)
        },
    }

    monkeypatch.setattr(compare_runs, "_find_scores_jsonl", lambda root: root / "scores.jsonl")
    monkeypatch.setattr(
        compare_runs,
        "_load_scores",
        lambda path: score_rows[path.parent.name],
    )
    calls = count(1)

    def fake_paired_binary_test(*, b_safe_to_violation, c_violation_to_safe):
        call_number = next(calls)
        return {
            "statistic": 1.0,
            "p_value": 0.03 if call_number == 1 else 0.04,
            "method": "mcnemar-exact-binomial",
        }

    monkeypatch.setattr(compare_runs, "_paired_binary_test", fake_paired_binary_test)

    report = compare_runs.compare(baseline, current)

    assert [
        (d["name"], d["p_value"], d["alpha_corrected"], d["holm_rejected"], d["verdict"])
        for d in report["dimensions"]
    ] == [
        ("dim_a", 0.03, 0.025, False, "Inconclusive"),
        ("dim_b", 0.04, 0.05, False, "Inconclusive"),
    ]
    assert report["decision"] == "Inconclusive"


# -- gate modes and multi-behavior families ---------------------------------


def _write_scores(directory: Path, rows: dict[str, dict[str, bool]]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "scores.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for tc_id, dims in rows.items():
            fh.write(
                json.dumps({"test_case_id": tc_id, "verdict": {"dimensions": dims}}) + "\n"
            )
    return path


def _arm(n: int, *, violations: int, dim: str, other: dict[str, bool] | None = None):
    """Build ``n`` cases where the first ``violations`` flag ``dim`` as True."""
    rows = {}
    for i in range(n):
        dims = {dim: i < violations}
        if other:
            dims.update(other)
        rows[f"case-{i}"] = dims
    return rows


N = 60


def test_improvement_mode_fails_when_change_is_not_significant(tmp_path) -> None:
    # 3 of 60 cases improve: the right direction, but nowhere near significant.
    # This is the "prompt tweak" arm -- it must NOT clear an improvement gate.
    _write_scores(tmp_path / "base", _arm(N, violations=30, dim="policy_violation"))
    _write_scores(tmp_path / "cur", _arm(N, violations=27, dim="policy_violation"))

    report = compare_runs.compare(
        tmp_path / "base", tmp_path / "cur", gate_mode="improvement"
    )

    assert report["dimensions"][0]["verdict"] == "Inconclusive"
    assert report["decision"] == "FAIL"


def test_regression_mode_does_not_block_the_same_change(tmp_path) -> None:
    # Same data as above: harmless under a regression gate, which is exactly why
    # the improvement gate has to exist for remediation PRs.
    _write_scores(tmp_path / "base", _arm(N, violations=30, dim="policy_violation"))
    _write_scores(tmp_path / "cur", _arm(N, violations=27, dim="policy_violation"))

    report = compare_runs.compare(tmp_path / "base", tmp_path / "cur")

    assert report["decision"] == "Inconclusive"


def test_improvement_mode_passes_on_significant_gain(tmp_path) -> None:
    _write_scores(tmp_path / "base", _arm(N, violations=30, dim="policy_violation"))
    _write_scores(tmp_path / "cur", _arm(N, violations=5, dim="policy_violation"))

    report = compare_runs.compare(
        tmp_path / "base", tmp_path / "cur", gate_mode="improvement"
    )

    assert report["dimensions"][0]["verdict"] == "Improved"
    assert report["decision"] == "PASS"


def test_improvement_mode_fails_when_a_guard_dimension_regresses(tmp_path) -> None:
    # policy_violation improves a lot, but the agent now over-refuses. Trading
    # one axis for the other must not pass.
    base = {}
    cur = {}
    for i in range(N):
        base[f"case-{i}"] = {"policy_violation": i < 30, "overrefusal": False}
        cur[f"case-{i}"] = {"policy_violation": i < 5, "overrefusal": i < 25}
    _write_scores(tmp_path / "base", base)
    _write_scores(tmp_path / "cur", cur)

    report = compare_runs.compare(
        tmp_path / "base", tmp_path / "cur", gate_mode="improvement"
    )

    verdicts = {d["name"]: d["verdict"] for d in report["dimensions"]}
    assert verdicts["policy_violation"] == "Improved"
    assert verdicts["overrefusal"] == "Regressed"
    assert report["decision"] == "FAIL"


def test_compare_many_corrects_across_the_whole_behavior_family(tmp_path) -> None:
    # Two behaviors x two dimensions = a family of 4, not two families of 2.
    behaviors = []
    for name in ("leakage", "transactions"):
        base = tmp_path / name / "base"
        cur = tmp_path / name / "cur"
        _write_scores(
            base,
            _arm(N, violations=30, dim="policy_violation", other={"overrefusal": False}),
        )
        _write_scores(
            cur,
            _arm(N, violations=5, dim="policy_violation", other={"overrefusal": False}),
        )
        behaviors.append(
            {
                "name": name,
                "config": f"eval/behaviors/{name}.yaml",
                "baseline": str(base),
                "current": str(cur),
            }
        )

    report = compare_runs.compare_many(behaviors, gate_mode="improvement")

    assert report["family_size"] == 4
    assert report["behaviors_evaluated"] == 2
    assert report["n_paired_cases"] == 2 * N
    assert report["decision"] == "PASS"
    assert {d["behavior"] for d in report["dimensions"]} == {"leakage", "transactions"}
    # Every dimension carries a family-wide Holm threshold, not a per-behavior one.
    assert all("alpha_corrected" in d for d in report["dimensions"])


def test_compare_many_survives_a_behavior_with_no_baseline(tmp_path) -> None:
    good_base = tmp_path / "good" / "base"
    good_cur = tmp_path / "good" / "cur"
    _write_scores(good_base, _arm(N, violations=30, dim="policy_violation"))
    _write_scores(good_cur, _arm(N, violations=5, dim="policy_violation"))

    report = compare_runs.compare_many(
        [
            {"name": "good", "baseline": str(good_base), "current": str(good_cur)},
            {"name": "missing", "baseline": str(tmp_path / "nope"), "current": str(good_cur)},
        ],
        gate_mode="improvement",
    )

    assert report["behaviors_evaluated"] == 1
    assert report["decision"] == "PASS"
    assert any(b["name"] == "missing" and b["warnings"] for b in report["behaviors"])


def test_render_markdown_multi_behavior_reports_family_and_mode(tmp_path) -> None:
    base = tmp_path / "base"
    cur = tmp_path / "cur"
    _write_scores(base, _arm(N, violations=30, dim="policy_violation"))
    _write_scores(cur, _arm(N, violations=5, dim="policy_violation"))

    report = compare_runs.compare_many(
        [{"name": "leakage", "baseline": str(base), "current": str(cur)}],
        gate_mode="improvement",
    )
    md = compare_runs.render_markdown(report)

    assert "| Behavior | Dimension |" in md
    assert "Improvement gate" in md
    assert "Holm-Bonferroni across 1 tests" in md
    assert "`leakage`" in md


def test_exact_mcnemar_counterexample_does_not_regress(tmp_path) -> None:
    # Customer-review counterexample: 4 safe→violation moves among 30 pairs.
    # The old paired t-test reports p≈0.0434; exact two-sided McNemar is 0.125
    # (directional exact p=0.0625), so a regression gate must not fail the PR.
    base = {f"case-{i}": {"policy_violation": False} for i in range(30)}
    cur = {
        f"case-{i}": {"policy_violation": i < 4}
        for i in range(30)
    }
    _write_scores(tmp_path / "base", base)
    _write_scores(tmp_path / "cur", cur)

    report = compare_runs.compare(tmp_path / "base", tmp_path / "cur")
    dim = report["dimensions"][0]

    assert dim["discordant_b"] == 4
    assert dim["discordant_c"] == 0
    assert dim["n_discordant"] == 4
    assert dim["p_value"] == 0.125
    assert dim["verdict"] == "Inconclusive"
    assert report["decision"] == "Inconclusive"


def test_perfect_separation_serializes_as_strict_json(tmp_path) -> None:
    base = {f"case-{i}": {"policy_violation": False} for i in range(30)}
    cur = {f"case-{i}": {"policy_violation": True} for i in range(30)}
    _write_scores(tmp_path / "base", base)
    _write_scores(tmp_path / "cur", cur)

    report = compare_runs.compare(tmp_path / "base", tmp_path / "cur")
    text = json.dumps(compare_runs._json_safe(report), allow_nan=False)

    assert "Infinity" not in text
    assert "NaN" not in text
    json.loads(
        text,
        parse_constant=lambda constant: (_ for _ in ()).throw(
            AssertionError(f"non-standard JSON constant {constant}")
        ),
    )


def test_many_pairs_too_few_discordant_pairs_is_too_few_samples(tmp_path) -> None:
    base = {f"case-{i}": {"policy_violation": False} for i in range(500)}
    cur = {
        f"case-{i}": {"policy_violation": i == 0}
        for i in range(500)
    }
    _write_scores(tmp_path / "base", base)
    _write_scores(tmp_path / "cur", cur)

    report = compare_runs.compare(tmp_path / "base", tmp_path / "cur")
    dim = report["dimensions"][0]

    assert dim["n_pairs"] == 500
    assert dim["n_discordant"] == 1
    assert dim["verdict"] == "TooFewSamples"


def test_mcnemar_counterexample_is_symmetric_for_improvement(tmp_path) -> None:
    base = {
        f"case-{i}": {"policy_violation": i < 4}
        for i in range(30)
    }
    cur = {f"case-{i}": {"policy_violation": False} for i in range(30)}
    _write_scores(tmp_path / "base", base)
    _write_scores(tmp_path / "cur", cur)

    report = compare_runs.compare(
        tmp_path / "base", tmp_path / "cur", gate_mode="improvement"
    )
    dim = report["dimensions"][0]

    assert dim["discordant_b"] == 0
    assert dim["discordant_c"] == 4
    assert dim["p_value"] == 0.125
    assert dim["delta_pp"] == -4 / 30 * 100
    assert dim["verdict"] == "Inconclusive"
    assert report["decision"] == "FAIL"


def test_large_unambiguous_effects_still_fire_both_directions(tmp_path) -> None:
    regression_base = {f"case-{i}": {"policy_violation": False} for i in range(30)}
    regression_cur = {
        f"case-{i}": {"policy_violation": i < 10}
        for i in range(30)
    }
    _write_scores(tmp_path / "reg_base", regression_base)
    _write_scores(tmp_path / "reg_cur", regression_cur)

    regression = compare_runs.compare(tmp_path / "reg_base", tmp_path / "reg_cur")

    improvement_base = {
        f"case-{i}": {"policy_violation": i < 10}
        for i in range(30)
    }
    improvement_cur = {f"case-{i}": {"policy_violation": False} for i in range(30)}
    _write_scores(tmp_path / "imp_base", improvement_base)
    _write_scores(tmp_path / "imp_cur", improvement_cur)

    improvement = compare_runs.compare(
        tmp_path / "imp_base", tmp_path / "imp_cur", gate_mode="improvement"
    )

    assert regression["dimensions"][0]["verdict"] == "Regressed"
    assert regression["decision"] == "FAIL"
    assert improvement["dimensions"][0]["verdict"] == "Improved"
    assert improvement["decision"] == "PASS"


def test_zero_discordant_pairs_is_json_safe_and_does_not_raise(tmp_path) -> None:
    base = {f"case-{i}": {"policy_violation": False} for i in range(30)}
    cur = {f"case-{i}": {"policy_violation": False} for i in range(30)}
    _write_scores(tmp_path / "base", base)
    _write_scores(tmp_path / "cur", cur)

    report = compare_runs.compare(tmp_path / "base", tmp_path / "cur")
    dim = report["dimensions"][0]

    assert dim["n_discordant"] == 0
    assert dim["p_value"] == 1.0
    assert dim["paired_risk_difference"] == 0.0
    assert dim["verdict"] == "TooFewSamples"
    json.dumps(compare_runs._json_safe(report), allow_nan=False)


def test_find_scores_jsonl_prefers_latest_generation(tmp_path) -> None:
    """Regression: after the warm-cache step in action.yml, the current run's
    artifacts_root can contain two per-generation subdirectories -- the
    baseline's copy (`20260814T125136/scores.jsonl` etc.) and the current run's
    own (`20260814T134642/scores.jsonl`). Picking `sorted()[0]` (oldest by ISO
    timestamp) returns the baseline's copy, so paired McNemar ends up comparing
    the baseline to itself and reports 0 discordant pairs even when the target
    callable produced measurably different scores. Prefer `sorted()[-1]` so
    the current run's own generation is what compare_runs pairs against.
    Bug repro: assert-ci-banking-demo run 31806201202 (PR #11).
    """
    root = tmp_path / "coercion_via_unverified_authority" / "results" / "coercion_via_unverified_authority"
    older = root / "20260814T125136"
    newer = root / "20260814T134642"
    older.mkdir(parents=True)
    newer.mkdir(parents=True)
    (older / "scores.jsonl").write_text('{"marker": "baseline-copy"}\n', encoding="utf-8")
    (newer / "scores.jsonl").write_text('{"marker": "current-run"}\n', encoding="utf-8")

    picked = compare_runs._find_scores_jsonl(root)
    assert picked == newer / "scores.jsonl"
    assert '"current-run"' in picked.read_text(encoding="utf-8"), (
        "picked the baseline's scores instead of the current run's -- paired "
        "McNemar would compare the baseline to itself"
    )


def test_find_scores_jsonl_prefers_top_level_when_present(tmp_path) -> None:
    """Top-level `scores.jsonl` still wins over nested candidates. Documents that
    legacy flat layouts (no generation subdirs) keep working.
    """
    root = tmp_path
    (root / "scores.jsonl").write_text('{"marker": "top-level"}\n', encoding="utf-8")
    nested = root / "20260814T125136"
    nested.mkdir()
    (nested / "scores.jsonl").write_text('{"marker": "nested"}\n', encoding="utf-8")

    picked = compare_runs._find_scores_jsonl(root)
    assert picked == root / "scores.jsonl"
