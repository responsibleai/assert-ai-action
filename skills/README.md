# ASSERT skill bundle

This directory is the canonical source for the customer-facing ASSERT coding-agent bundle installed by [`ONBOARD.md`](../ONBOARD.md).

## Install paths in a user repository

| Assistant | Source in this repo | Destination in the user's repo |
|---|---|---|
| Claude Code | `skills/<name>/SKILL.md` | `.claude/skills/<name>/SKILL.md` |
| GitHub Copilot CLI | `skills/<name>/<name>.prompt.md` | `.github/prompts/<name>.prompt.md` |
| Cursor | `skills/<name>/*.mdc` | `.cursor/rules/<name>.mdc` |

## Skills

- `wire-assert-ci` **(lives here)** owns repository scanning, target wrapping, draft spec extraction and confirmation, behavior splitting, CI workflow authoring, the baseline/config commit, and the ACS remediation PR flow.
- `run-assert-eval` **(lives upstream in [`responsibleai/ASSERT`](https://github.com/responsibleai/ASSERT))** owns `assert-ai init`, live pipeline runs, result reporting, Results Q&A, and viewer hand-off.

`run-assert-eval` is **installed from upstream, never vendored here.** It used to be
copied into this directory, and within weeks the two copies had drifted in opposite
directions — the copy here had dropped upstream's `target.endpoint` guidance, while
upstream still told users to run an editable install of their own repo. Neither side
noticed, because nothing checked.

Because it is owned elsewhere and keeps changing, the only durable fix is not to have
a copy at all. `scripts/check_bundle.py` fails the build if `skills/run-assert-eval/`
reappears, or if any file here declares that skill name.

Installing the bundle therefore takes **two commands, one per source repo**:

```bash
npx skills add responsibleai/ASSERT --skill run-assert-eval --yes
npx skills add responsibleai/assert-ai-action --skill wire-assert-ci --yes
```

`skills add` takes one package per invocation and silently ignores extras while still
exiting 0 — a combined command looks successful and installs half the bundle.

The target decision tree stays in the ASSERT docs: <https://github.com/responsibleai/ASSERT/blob/main/docs/targets/README.md>.

## BYO credentials

There is no shared endpoint. Users provide their own provider credentials as repository secrets/environment variables such as `AZURE_API_KEY`, `AZURE_API_BASE`, `AZURE_API_VERSION`, or `OPENAI_API_KEY`. Never store credential values in configs, workflows, prompts, or logs.
