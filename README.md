# ASSERT safety regression gate

A composite GitHub Action that runs `assert-ai` evals on every PR and gates merges against safety regressions detected with a paired-binary McNemar test. It installs `assert-ai` from PyPI, runs a live eval for each behavior, compares the current runs to a cached baseline, and publishes JSON/Markdown artifacts.

ASSERT configs are written **one behavior per YAML**, so the gate takes a glob and evaluates each behavior independently — while correcting for multiple comparisons across the whole set.


## Coding-agent onboarding

Two ways in. Both end with a working gate; pick based on whether you have Node.

### Option 1 — install the skills (recommended, 40+ agents)

Requires Node.js ≥ 22 (the `skills` CLI uses `node:util`'s `styleText`, added in Node 22). On Node 18/20 you'll see `SyntaxError: The requested module 'node:util' does not provide an export named 'styleText'` — use [Option 2](#option-2--paste-one-url-no-install-no-node) instead, or upgrade Node.

```bash
npx skills add responsibleai/ASSERT --skill run-assert-eval --yes
npx skills add responsibleai/assert-ai-action --skill wire-assert-ci --yes
```

Installs `wire-assert-ci` and `run-assert-eval` for Cursor, Claude Code, GitHub Copilot, Gemini CLI, Amp, Windsurf, Codex, and [40+ other agents](https://github.com/vercel-labs/skills#supported-agents). Drop the flags for an interactive picker.

Two commands because the bundle spans two repos on purpose: `run-assert-eval` is owned upstream in [`responsibleai/ASSERT`](https://github.com/responsibleai/ASSERT) and installed from there rather than copied here, so it never goes stale. Run them separately — `skills add` takes one package per invocation and silently ignores extras while still exiting 0.

Then just say what you want:

> Use the `wire-assert-ci` skill to add an ASSERT safety gate to this repo.

### Option 2 — paste one URL (no install, no Node)

```text
read https://raw.githubusercontent.com/responsibleai/assert-ai-action/main/ONBOARD.md
```

Works in Copilot CLI, Claude Code, and Cursor. The agent fetches the skill files itself.

### What happens next

Either way, the agent scans your repo, picks the highest-fidelity way to reach your agent (auto-traced → bring-your-own-trace → callable → HTTP endpoint → prompt-agent), drafts an eval spec from your own README and prompts, **asks you to confirm or replace it**, splits it one behavior per YAML, runs a baseline, and opens the gate PR.

You bring your own model credentials as repository secrets — `AZURE_API_KEY`, `AZURE_API_BASE`, `AZURE_API_VERSION`, or `OPENAI_API_KEY`. There is no shared endpoint.

## Quickstart

Create `.github/workflows/safety-gate.yml`:

```yaml
name: Safety regression gate
on:
  pull_request:
    branches: [main]
  push:
    branches: [main]
  schedule:
    - cron: '0 7 * * *'

jobs:
  safety:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write
      actions: read          # required so the action can find the baseline run
    steps:
      - uses: actions/checkout@v4
        with:
          persist-credentials: false
      - uses: responsibleai/assert-ai-action@v1
        with:
          configs: eval/behaviors/*.yaml
          baseline: assert-ai-baseline
          min-pairs: '30'
          extras: regression,otel
          target-install: python -m pip install -e .
          provider-env: |
            AZURE_API_KEY=${{ secrets.AZURE_API_KEY }}
            AZURE_API_BASE=${{ secrets.AZURE_API_BASE }}
            AZURE_API_VERSION=${{ secrets.AZURE_API_VERSION }}
      - if: github.event_name != 'pull_request'
        uses: actions/upload-artifact@v4
        with:
          name: assert-ai-baseline
          path: assert-ai-artifacts/
          retention-days: 90
```

First run on `main` creates the baseline artifact. PR runs locate that baseline and compare paired `test_case_id` rows. `target-install` installs the repository under test so `target.callable` can import it, including `src/` layouts. Set `extras` for your target route: `regression,otel` for traced callables, `regression,otel,langgraph` for LangGraph, `regression,aiohttp` for native `target.endpoint`, or `regression` for plain model targets.

You do **not** need a `download-artifact` step. Artifacts are scoped to the run that produced them, so a PR cannot see the default branch's baseline on its own; the action resolves the most recent successful run on the default branch that still holds the artifact and downloads it for you. That needs `actions: read`. Point `baseline` at a directory instead if you prefer to commit baselines to the repo.

## Inputs

| Input | Required | Default | Description |
|---|---:|---|---|
| `configs` | yes\* | — | Path, glob, or newline-delimited list of `assert-ai` YAML eval configs. One behavior per file. |
| `config` | no | `''` | **Deprecated** single-config alias for `configs`. |
| `gate-mode` | no | `regression` | `regression` blocks on significant regressions; `improvement` passes only on a significant gain. See [Gate modes](#gate-modes). |
| `primary-dimension` | no | `policy_violation` | Dimension that must improve under `gate-mode: improvement`. |
| `guard-dimensions` | no | `overrefusal` | Comma-separated dimensions that must not regress. |
| `alpha` | no | `0.05` | Family-wise significance level for the Holm-Bonferroni correction. |
| `min-pairs` | no | `30` | Minimum paired cases required for a dimension to receive a statistical verdict. Fewer pairs reports `TooFewSamples`, a non-verdict. |
| `baseline` | no | `''` | Path to a baseline run directory, or the **name** of an artifact from a trusted run. |
| `baseline-branch` | no | `''` | Branch whose successful runs hold the baseline artifact. Defaults to the repo default branch. |
| `assert-ai-version` | no | `0.1.0` | Version of `assert-ai` to install from PyPI. |
| `provider-env` | no | `''` | Newline-delimited `KEY=VALUE` pairs for any LiteLLM provider. Values are masked. |
| `azure-api-key` | no | `''` | Exposed as `AZURE_API_KEY` during the eval. |
| `azure-api-base` | no | `''` | Exposed as `AZURE_API_BASE` during the eval. |
| `azure-api-version` | no | `''` | Exposed as `AZURE_API_VERSION` during the eval. |
| `post-pr-comment` | no | `true` | Upsert a Markdown gate report on pull requests. |
| `comment-marker` | no | `<!-- assert-ai-gate -->` | Marker used to update one stable PR comment. |
| `fail-on-regression` | no | `true` | Exit 1 when the verdict is `FAIL`. |
| `allow-inconclusive` | no | `true` | Labeling only. When false, insignificant dimensions are reported as `Uncertain` and the top-level verdict becomes `WARN` instead of `Inconclusive`. Does **not** change job pass/fail — see [`docs/verdicts.md`](docs/verdicts.md). |
| `extras` | no | `regression` | Comma-separated PyPI extras, e.g. `regression,otel,langgraph`. |
| `target-install` | no | `''` | Shell command run before the eval to install the repository under test, e.g. `python -m pip install -e .`. |

## Outputs

| Output | Description |
|---|---|
| `gate-verdict` | `PASS`, `WARN`, `FAIL`, `FirstRun`, `TestSetChanged`, or `Inconclusive`. |
| `gate-report-path` | Path to `gate_report.json`. |
| `n-paired-cases` | Number of paired cases used by the paired-binary test. |
| `behaviors-evaluated` | Number of behavior configs that produced a comparable run. |
| `pr-comment-url` | URL of the posted or updated PR comment, if posted. |

## Gate modes

The default gate blocks only on evidence of harm. That is the right default for ordinary pull requests, but it is the wrong tool for a PR whose entire purpose is to *fix* a measured safety problem — under a regression gate, a remediation that does nothing at all passes.

| Mode | Passes when |
|---|---|
| `regression` (default) | No `(behavior × dimension)` regressed significantly. |
| `improvement` | `primary-dimension` improved significantly in at least one behavior **and** no `guard-dimensions` regressed. |

The asymmetry is deliberate: under `regression` a change that merely trends worse is not blocked; under `improvement` a change that merely trends better does not pass. See [`examples/improvement-gate-workflow.yml`](examples/improvement-gate-workflow.yml).

## Multiple behaviors and multiple comparisons

Every matched config is one behavior, run and paired independently. The Holm-Bonferroni step-down correction is then applied across the **whole `(behavior × dimension)` family** rather than per behavior — correcting each behavior separately would quietly inflate the family-wise false-positive rate as behaviors are added. The PR comment states the correction and the family size.

Each behavior also gets its own `artifacts_root`, and baselines are matched to their own suite, so adding a second behavior cannot cause the gate to compare a suite against itself.

## Verdicts

| Verdict | Meaning |
|---|---|
| `PASS` | No safety regression; at least one dimension improved or all checks are clean. |
| `WARN` | The gate needs attention but does not block by default. |
| `FAIL` | A paired dimension regressed significantly (or, in `improvement` mode, failed to improve). |
| `FirstRun` | No baseline exists yet. |
| `TestSetChanged` | The current `test_set.jsonl` does not match the baseline. |
| `Inconclusive` | The paired test found no statistically significant movement. |

See [`docs/verdicts.md`](docs/verdicts.md) for details.


## Sample size and `TooFewSamples`

A smoke run can be small to prove wiring, imports, and credentials. A committed gate needs at least `min-pairs` paired cases per behavior (default 30; use about 40 for margin). If a dimension has fewer paired cases, it is reported `TooFewSamples`, which is a non-verdict and does not protect the PR. Lower `min-pairs` only deliberately, and understand that it weakens statistical power. Real gates can take tens of minutes and provider spend, not seconds.

## Security and trust model

This action runs PR-authored code with model/provider credentials available in the job environment. `::add-mask::` redacts exact secret strings in logs, but it does not prevent code from exfiltrating secrets over the network. Use it only for PRs whose code you are willing to execute with those credentials; fork PRs normally do not receive secrets, so the gate cannot run a real evaluation there.

The uploaded `assert-ai-artifacts/` include raw model inputs, outputs, scores, and supporting eval data. The examples retain them for up to 30 or 90 days depending on the workflow; reduce retention or use private repositories if those artifacts may contain sensitive prompts, user data, or proprietary outputs. Prefer `actions/checkout` with `persist-credentials: false` so the checked-out workspace does not retain a write-capable GitHub token.

## Baseline lifecycle

Baselines are normal GitHub Actions artifacts from trusted runs on the default branch. They contain `scores.jsonl`, `test_set.jsonl`, and supporting ASSERT artifacts. PRs compare against the latest trusted baseline; scheduled runs refresh it to catch model or dependency changes. See [`docs/baseline-lifecycle.md`](docs/baseline-lifecycle.md).

## Versioning and compatibility

`assert-ai-version` defaults to `0.1.0`; override it to move independently of the action. Use `responsibleai/assert-ai-action@v1` for the floating major tag with compatible bug fixes, or pin an exact tag such as `@v1.0.0`.

Release tags use semantic versions, and the floating major tag must point to the same commit as the latest compatible exact tag. See [`docs/release-procedure.md`](docs/release-procedure.md) before cutting or moving release tags.

## Contributing and license

Contributions are welcome through pull requests. Licensed under the [MIT License](LICENSE).
