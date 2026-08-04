"""The dependency on `run-assert-eval` must be real, not documented.

`wire-assert-ci` delegates every live evaluation to `run-assert-eval`, which is
owned upstream in responsibleai/ASSERT. We deliberately do not vendor a copy --
an earlier copy drifted from upstream in both directions within weeks.

That leaves a gap: nothing in the skills spec expresses "this skill needs that
one". The frontmatter carries only `name`, `description` and `allowed-tools`.
Prose in SKILL.md telling an agent to install the other half is a convention an
agent may or may not follow, not a dependency.

`skills-lock.json` is the mechanism that makes it real. `npx skills
experimental_install` restores every entry in it, across repositories, in one
command, and `npx skills update` keeps both current afterwards. So the lock file
is the dependency declaration, and these tests are what stop it from rotting.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "skills-lock.json"

SELF_REPO = "responsibleai/assert-ai-action"
UPSTREAM_REPO = "responsibleai/ASSERT"
UPSTREAM_SKILL = "run-assert-eval"
LOCAL_SKILL = "wire-assert-ci"


@pytest.fixture(scope="module")
def lock() -> dict:
    assert LOCK.is_file(), "skills-lock.json is the dependency declaration; it must exist"
    return json.loads(LOCK.read_text(encoding="utf-8"))


def test_lock_declares_both_halves_of_the_bundle(lock: dict) -> None:
    """One command must yield a working bundle, not half of one."""
    skills = lock.get("skills", {})

    assert LOCAL_SKILL in skills, f"{LOCAL_SKILL} missing from skills-lock.json"
    assert UPSTREAM_SKILL in skills, (
        f"{UPSTREAM_SKILL} missing from skills-lock.json. Without it, "
        f"`skills experimental_install` yields {LOCAL_SKILL} with nothing to "
        "delegate evaluation to, and the failure only surfaces mid-run."
    )


def test_upstream_skill_is_sourced_from_assert_not_vendored_here(lock: dict) -> None:
    """Pointing this entry at our own repo would re-create the fork we removed."""
    entry = lock["skills"][UPSTREAM_SKILL]

    assert entry["source"] == UPSTREAM_REPO, (
        f"{UPSTREAM_SKILL} is sourced from {entry['source']!r}. It is owned by "
        f"{UPSTREAM_REPO}; sourcing it anywhere else re-introduces a copy that "
        "will silently drift."
    )


def test_local_skill_points_at_a_file_that_exists(lock: dict) -> None:
    entry = lock["skills"][LOCAL_SKILL]

    assert entry["source"] == SELF_REPO
    assert (ROOT / entry["skillPath"]).is_file(), (
        f"skills-lock.json points at {entry['skillPath']}, which is not in this repo"
    )


def test_lock_has_no_stale_personal_namespace_reference(lock: dict) -> None:
    """The repo moved into the org; a lock still naming the personal copy would
    quietly keep installing from the repo we are retiring."""
    for name, entry in lock["skills"].items():
        assert not entry["source"].startswith("changliu2/"), (
            f"{name} still sourced from {entry['source']}"
        )


def test_every_lock_entry_resolves_over_https(lock: dict) -> None:
    """A path that 404s makes the whole install fail for a customer, and nothing
    else here would catch a typo in it."""
    for name, entry in lock["skills"].items():
        url = (
            "https://raw.githubusercontent.com/"
            f"{entry['source']}/main/{entry['skillPath']}"
        )
        try:
            with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310
                body = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            # A 404 is the bug this test exists to catch -- a lock entry pointing
            # at a path that does not exist breaks the install for every
            # customer. HTTPError subclasses URLError, so it must be handled
            # first or the skip below would swallow it.
            pytest.fail(f"{name}: {url} -> HTTP {exc.code}")
        except (urllib.error.URLError, TimeoutError) as exc:
            pytest.skip(f"network unavailable: {exc}")

        assert body.lstrip().startswith("---"), (
            f"{name}: {url} did not return a SKILL.md with YAML frontmatter"
        )
        assert re.search(rf"^name:\s*{re.escape(name)}\s*$", body, re.M), (
            f"{name}: {url} resolves, but its frontmatter declares a different name"
        )


def test_onboard_documents_the_one_command_restore() -> None:
    """The lock file only helps if a reader is told it exists."""
    onboard = (ROOT / "ONBOARD.md").read_text(encoding="utf-8")

    assert "skills-lock.json" in onboard
    assert "experimental_install" in onboard
