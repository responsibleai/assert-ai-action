"""Verify every raw URL in ONBOARD.md resolves to a real file.

Both cold-read testers hit 404s on these URLs. That was attributed to the repo
being private and the branch unmerged -- but if a path is also simply wrong, it
will still 404 after publishing, and the bugbash dies on the first line the
user pastes.

The bundle spans two repositories on purpose: `wire-assert-ci` lives here, and
`run-assert-eval` is owned upstream in responsibleai/ASSERT and is linked, never
copied, so it cannot go stale. So this check has two halves:

  * URLs pointing at this repo are resolved against the working tree, which
    catches a wrong path before it is ever published.
  * URLs pointing at upstream ASSERT are resolved over HTTPS, because there is
    no local copy to compare against -- that is the whole point.

Set ASSERT_SKIP_NETWORK=1 to skip the upstream half when offline.
"""

import io
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
onboard = io.open(ROOT / "ONBOARD.md", encoding="utf-8").read()

SELF_REPO = "responsibleai/assert-ai-action"
UPSTREAM_REPO = "responsibleai/ASSERT"

RAW_ANY = r"https://raw\.githubusercontent\.com/([^/]+/[^/]+)/([^/]+)/(\S+?)(?=[\s`)]|$)"

problems: list[str] = []
matches = re.findall(RAW_ANY, onboard)
if not matches:
    problems.append("ONBOARD.md contains no raw skill URLs at all")

self_urls: set[str] = set()
upstream_urls: set[str] = set()

print(f"{len(matches)} raw URL(s) found in ONBOARD.md\n")
for repo, ref, rel in matches:
    if ref != "main":
        problems.append(f"{rel}: pinned to '{ref}', not 'main'")

    if repo == SELF_REPO:
        self_urls.add(rel)
        ok = (ROOT / rel).is_file()
        print(f"  [{'OK ' if ok else 'MISSING'}] local    {repo}/{rel}")
        if not ok:
            problems.append(f"{rel}: no such file in this repo")
    elif repo == UPSTREAM_REPO:
        upstream_urls.add(rel)
        if os.environ.get("ASSERT_SKIP_NETWORK"):
            print(f"  [SKIP] upstream {repo}/{rel}")
            continue
        url = f"https://raw.githubusercontent.com/{repo}/{ref}/{rel}"
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310
                ok = resp.status == 200 and len(resp.read()) > 0
        except (urllib.error.URLError, TimeoutError) as exc:
            ok = False
            problems.append(f"{rel}: upstream fetch failed ({exc})")
        print(f"  [{'OK ' if ok else 'DEAD'}] upstream {repo}/{rel}")
        if not ok:
            problems.append(f"{rel}: not reachable in {repo}")
    else:
        problems.append(f"{rel}: unexpected host repo '{repo}'")

# The install destinations the skill writes into the user's repo must match the
# conventions each assistant actually loads from.
EXPECTED_DESTS = {
    ".claude/skills/wire-assert-ci/SKILL.md",
    ".claude/skills/run-assert-eval/SKILL.md",
    ".github/prompts/wire-assert-ci.prompt.md",
    ".github/prompts/run-assert-eval.prompt.md",
    ".cursor/rules/assert-ci.mdc",
    ".cursor/rules/assert.mdc",
}
for d in sorted(EXPECTED_DESTS):
    if d not in onboard:
        problems.append(f"ONBOARD.md never names install destination {d}")

# Every skill file in this repo should be reachable from ONBOARD.md, or a user
# on that assistant silently gets a partial install.
for p in sorted((ROOT / "skills").rglob("*")):
    if p.is_file() and p.suffix in {".md", ".mdc"} and p.name != "README.md":
        rel = p.relative_to(ROOT).as_posix()
        if rel not in self_urls:
            problems.append(f"{rel} exists but ONBOARD.md never fetches it")

# The upstream half must actually be present. If someone "simplifies" ONBOARD.md
# by dropping the ASSERT URLs, users get wire-assert-ci with nothing to delegate
# the evaluation to, and the failure only shows up mid-run.
if not upstream_urls:
    problems.append(
        f"ONBOARD.md fetches nothing from {UPSTREAM_REPO}; run-assert-eval "
        "would be missing and wire-assert-ci has nothing to delegate to"
    )

print()
if problems:
    print(f"{len(problems)} PROBLEM(S):")
    for p in problems:
        print("  -", p)
    sys.exit(1)
print("ONBOARD.md paths and install destinations are all consistent.")
