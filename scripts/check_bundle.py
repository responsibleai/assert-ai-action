"""Verify the skill bundle stays consistent with the shipped action contract.

Catches the two ways this bundle rots: a skill telling an agent to emit a
workflow input the action does not have, and the three front-doors drifting
apart so Copilot, Claude, and Cursor users get different behaviour.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
FAILURES: list[str] = []


def fail(msg: str) -> None:
    FAILURES.append(msg)
    print(f"FAIL {msg}")


def check_frontmatter() -> None:
    for path in sorted(ROOT.glob("skills/*/*")):
        if path.suffix not in {".md", ".mdc"}:
            continue
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            continue
        _, _, rest = text.partition("---\n")
        block, sep, _ = rest.partition("\n---")
        if not sep:
            fail(f"{path.name}: unterminated frontmatter")
            continue
        try:
            meta = yaml.safe_load(block)
        except yaml.YAMLError as exc:
            fail(f"{path.name}: frontmatter does not parse: {exc}")
            continue
        if not isinstance(meta, dict):
            fail(f"{path.name}: frontmatter is not a mapping")


def action_inputs() -> set[str]:
    action = yaml.safe_load((ROOT / "action.yml").read_text(encoding="utf-8"))
    return set(action["inputs"])


def check_workflow_snippets(valid: set[str]) -> None:
    pattern = re.compile(r"```yaml\n(.*?)```", re.DOTALL)
    targets = list(ROOT.glob("skills/**/*.md")) + list(ROOT.glob("skills/**/*.mdc"))
    targets += list(ROOT.glob("examples/*.yml")) + [ROOT / "README.md"]

    for path in sorted(set(targets)):
        text = path.read_text(encoding="utf-8")
        blocks = (
            [text] if path.suffix in {".yml", ".yaml"} else pattern.findall(text)
        )
        for i, block in enumerate(blocks):
            if "responsibleai/assert-ai-action" not in block:
                continue
            # GitHub expressions are not valid YAML scalars in every position;
            # neutralise them before parsing.
            sanitised = re.sub(r"\$\{\{.*?\}\}", "EXPR", block, flags=re.DOTALL)
            try:
                doc = yaml.safe_load(sanitised)
            except yaml.YAMLError as exc:
                fail(f"{path.name} block {i}: invalid YAML: {exc}")
                continue
            for step in _walk_steps(doc):
                uses = str(step.get("uses", ""))
                if "responsibleai/assert-ai-action" not in uses:
                    continue
                if not re.search(r"@v\d", uses):
                    fail(f"{path.name} block {i}: action is not pinned to a major tag: {uses}")
                for key in (step.get("with") or {}):
                    if key not in valid:
                        fail(f"{path.name} block {i}: unknown action input '{key}'")


def _walk_steps(doc: object):
    if isinstance(doc, dict):
        for key, value in doc.items():
            if key == "steps" and isinstance(value, list):
                for step in value:
                    if isinstance(step, dict):
                        yield step
            else:
                yield from _walk_steps(value)
    elif isinstance(doc, list):
        for item in doc:
            yield from _walk_steps(item)


def check_front_doors_agree() -> None:
    """All three shapes of a skill must mention the same load-bearing concepts."""
    concepts = [
        "Rung 1",
        "Rung 3",
        "judge-traces",
        "eval/behaviors",
        "gate-mode",
        "improvement",
        "acs generate",
        "auto_trace",
    ]
    for skill in ("wire-assert-ci",):
        files = sorted((ROOT / "skills" / skill).glob("*"))
        if not files:
            fail(f"{skill}: no front-door files found")
            continue
        texts = {f.name: f.read_text(encoding="utf-8") for f in files}
        for concept in concepts:
            present = {name for name, text in texts.items() if concept in text}
            if present and len(present) != len(texts):
                missing = sorted(set(texts) - present)
                fail(f"{skill}: '{concept}' missing from {missing}")


# Skills owned by responsibleai/ASSERT. They are linked, never copied: Alex keeps
# updating them, and a copy here silently forks. An earlier vendored copy of
# run-assert-eval drifted in both directions within weeks -- it had dropped
# upstream's target.endpoint guidance while upstream still told users to run an
# editable install of their own repo. Neither side noticed, because nothing
# checked. This makes re-introducing that copy a build failure.
UPSTREAM_OWNED_SKILLS = {"run-assert-eval"}


def check_no_vendored_upstream_skill() -> None:
    for skill in sorted(UPSTREAM_OWNED_SKILLS):
        local = ROOT / "skills" / skill
        if local.exists():
            fail(
                f"skills/{skill}/ is owned by responsibleai/ASSERT and must not be "
                "vendored here -- it will silently fork. Delete the directory and "
                "let ONBOARD.md install it from upstream instead."
            )

    # A copy can also creep back in under a different directory name, so match on
    # the skill's declared frontmatter name rather than on the path.
    for path in sorted(ROOT.glob("skills/*/*.md")):
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            continue
        _, _, rest = text.partition("---")
        block, _, _ = rest.partition("---")
        try:
            meta = yaml.safe_load(block) or {}
        except yaml.YAMLError:
            continue
        name = meta.get("name")
        if name in UPSTREAM_OWNED_SKILLS:
            fail(
                f"{path.relative_to(ROOT)} declares name '{name}', which is owned "
                "by responsibleai/ASSERT. Link to it; do not vendor it."
            )


def check_no_wrong_repo_name() -> None:
    # The archived repo. Any surviving reference resolves to nothing at runtime.
    wrong = "responsibleai/assert" + "-action"
    for path in ROOT.rglob("*"):
        if ".git" in path.parts or not path.is_file():
            continue
        if path.suffix not in {".md", ".mdc", ".yml", ".yaml", ".py"}:
            continue
        if wrong in path.read_text(encoding="utf-8", errors="ignore"):
            fail(f"{path.relative_to(ROOT)}: references the wrong repo name '{wrong}'")


def check_onboard_urls() -> None:
    onboard = (ROOT / "ONBOARD.md").read_text(encoding="utf-8")
    urls = re.findall(r"main/(skills/[^\s`]+)", onboard)
    if not urls:
        fail("ONBOARD.md: no skill URLs found")
    for rel in urls:
        if not (ROOT / rel).is_file():
            fail(f"ONBOARD.md: points at a file that does not exist: {rel}")


def main() -> int:
    check_frontmatter()
    check_workflow_snippets(action_inputs())
    check_front_doors_agree()
    check_no_wrong_repo_name()
    check_no_vendored_upstream_skill()
    check_onboard_urls()
    if FAILURES:
        print(f"\n{len(FAILURES)} problem(s)")
        return 1
    print("skill bundle OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
