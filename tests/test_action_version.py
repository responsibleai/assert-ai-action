"""The version stamped into gate reports must be one we actually released.

Both compare_runs.py and detect_test_set_drift.py hardcoded "v1.0.0-rc1" and
kept saying so through v1.0.0, v1.0.1 and v1.0.2. Every gate report a customer
produced therefore carried a version that never existed -- the one field you
reach for first when reproducing a reported failure.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEMVER = re.compile(r"^v\d+\.\d+\.\d+$")


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_version_is_a_plain_release_tag() -> None:
    version = load("_version").ACTION_VERSION

    assert SEMVER.match(version), (
        f"ACTION_VERSION is {version!r}. Gate reports should be stamped with a "
        "released tag, not a pre-release or a bare major."
    )


def test_both_report_writers_agree() -> None:
    """They drifted precisely because the constant was duplicated."""
    expected = load("_version").ACTION_VERSION

    assert load("compare_runs").ACTION_VERSION == expected
    assert load("detect_test_set_drift").ACTION_VERSION == expected
    assert load("write_firstrun_report").ACTION_VERSION == expected


def test_version_matches_the_newest_release_tag() -> None:
    """Catches a release cut without bumping the constant.

    Skips when tags are unavailable, which is the case for a shallow CI checkout.
    """
    try:
        tags = subprocess.run(
            ["git", "tag", "--list", "v*.*.*"],
            cwd=ROOT, capture_output=True, text=True, timeout=30, check=True,
        ).stdout.split()
    except (subprocess.SubprocessError, OSError):
        return
    releases = sorted(
        (t for t in tags if SEMVER.match(t)),
        key=lambda t: tuple(int(p) for p in t[1:].split(".")),
    )
    if not releases:
        return

    assert load("_version").ACTION_VERSION == releases[-1], (
        f"ACTION_VERSION is {load('_version').ACTION_VERSION}, newest tag is "
        f"{releases[-1]}. Bump scripts/_version.py when cutting a release."
    )


def test_the_stamp_actually_reaches_a_gate_report() -> None:
    """A constant nothing writes out would pass every check above and still be useless."""
    for name in ("compare_runs", "write_firstrun_report"):
        source = (ROOT / "scripts" / f"{name}.py").read_text(encoding="utf-8")
        assert '"action_version": ACTION_VERSION' in source, name
