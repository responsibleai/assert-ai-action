Read and follow this bootstrap exactly. Your job is to install the ASSERT coding-agent bundle into the current repository, then invoke `wire-assert-ci`.

BYO keys are required: there is no shared ASSERT endpoint. The user must provide provider credentials as repository secrets/environment variables such as `AZURE_API_KEY`, `AZURE_API_BASE`, `AZURE_API_VERSION`, `OPENAI_API_KEY`, or the names required by their LiteLLM provider. Never read or write credential values.

## Step 1 — install the skills

This bundle is **two skills from two repositories**, and that is deliberate:
`run-assert-eval` is owned upstream in `responsibleai/ASSERT` and is installed
from there, never copied here, so you always get the current version.

**Preferred.** If Node is available, run **both** commands, then skip to Step 2.
They cover 40+ agents and detect the host automatically:

```bash
npx skills add responsibleai/ASSERT --skill run-assert-eval --yes
npx skills add responsibleai/assert-ai-action --skill wire-assert-ci --yes
```

Run them as two separate commands. `skills add` accepts only one package per
invocation and **silently ignores extra ones while still exiting 0**, so a
combined command looks like it worked and leaves you with half the bundle.

**One command instead, if you would rather not rely on that.** This repo ships a
[`skills-lock.json`](skills-lock.json) declaring both halves and where each comes
from, so a single restore installs the whole bundle and cannot leave you with
part of it:

```bash
curl -O https://raw.githubusercontent.com/responsibleai/assert-ai-action/main/skills-lock.json
npx skills experimental_install
```

Commit that lock file and `npx skills update` afterwards keeps **both** skills
current, including `run-assert-eval` as it changes upstream in ASSERT.

**Fallback.** Only if `npx` is unavailable or the commands fail, detect the
assistant and fetch the matching files by hand. Note the two different hosts:

- Claude Code:
  - `https://raw.githubusercontent.com/responsibleai/assert-ai-action/main/skills/wire-assert-ci/SKILL.md` -> `.claude/skills/wire-assert-ci/SKILL.md`
  - `https://raw.githubusercontent.com/responsibleai/ASSERT/main/.claude/skills/run-assert-eval/SKILL.md` -> `.claude/skills/run-assert-eval/SKILL.md`
- GitHub Copilot CLI:
  - `https://raw.githubusercontent.com/responsibleai/assert-ai-action/main/skills/wire-assert-ci/wire-assert-ci.prompt.md` -> `.github/prompts/wire-assert-ci.prompt.md`
  - `https://raw.githubusercontent.com/responsibleai/ASSERT/main/.github/prompts/run-assert-eval.prompt.md` -> `.github/prompts/run-assert-eval.prompt.md`
- Cursor:
  - `https://raw.githubusercontent.com/responsibleai/assert-ai-action/main/skills/wire-assert-ci/assert-ci.mdc` -> `.cursor/rules/assert-ci.mdc`
  - `https://raw.githubusercontent.com/responsibleai/ASSERT/main/.cursor/rules/assert.mdc` -> `.cursor/rules/assert.mdc`

Create parent directories if missing. Do not overwrite unrelated local files without showing the diff first.

## Step 2 — run the skill

Invoke the `wire-assert-ci` skill and follow it until it either opens an ACS remediation PR or stops for required user confirmation.
