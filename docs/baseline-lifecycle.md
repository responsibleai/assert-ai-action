# Baseline lifecycle

A baseline is the trusted ASSERT artifact set that PRs compare against. It must contain at least:

- `scores.jsonl` — judge verdicts for each test case.
- `test_set.jsonl` — the exact generated cases used for pairing.
- `metrics.json` — aggregate run metrics, useful for humans.

## How baselines are produced

Run the action on `main` after a trusted merge, then upload `assert-ai-artifacts/` as a GitHub Actions artifact named `assert-ai-baseline`.

```yaml
jobs:
  safety:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write
      actions: read
    steps:
      - uses: actions/checkout@v4
        with:
          persist-credentials: false
      - uses: responsibleai/assert-ai-action@v1
        with:
          configs: eval/behaviors/*.yaml
          baseline: assert-ai-baseline
          min-pairs: '30'
          target-install: python -m pip install -e .
          extras: regression,otel
          azure-api-key: ${{ secrets.AZURE_API_KEY }}
          azure-api-base: ${{ secrets.AZURE_API_BASE }}
          azure-api-version: ${{ secrets.AZURE_API_VERSION }}
      - uses: actions/upload-artifact@v4
        with:
          name: assert-ai-baseline
          path: assert-ai-artifacts/
          retention-days: 90
```

## How baselines are refreshed

Use both `push` to `main` and a nightly `schedule`. The push path captures code changes. The scheduled path catches model, prompt dependency, and tool-backend drift even when code is unchanged.

## How PRs consume baselines

Do not add a manual `actions/download-artifact` step. GitHub Actions artifacts are scoped to the run that produced them, so a PR run cannot see the default branch baseline by name. Pass the artifact name through `baseline`; the action uses `actions: read` permission to find the latest successful trusted run on `baseline-branch` and downloads the artifact itself.

```yaml
jobs:
  safety:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write
      actions: read
    steps:
      - uses: actions/checkout@v4
        with:
          persist-credentials: false
      - uses: responsibleai/assert-ai-action@v1
        with:
          configs: eval/behaviors/*.yaml
          baseline: assert-ai-baseline
          min-pairs: '30'
          target-install: python -m pip install -e .
          extras: regression,otel
```

If no trusted artifact is available, the action returns `FirstRun` and still uploads the current artifacts on non-PR runs.

## Test-set drift

The paired-binary comparison is valid only when baseline and current runs score the same cases. The action compares SHA256 hashes of `test_set.jsonl`:

- same hash: run the paired gate.
- different hash: return `TestSetChanged` and skip the paired comparison.

Treat `TestSetChanged` as a baseline-refresh PR. Review why the cases changed, merge if expected, then let the next `main` run publish the new baseline.

## Manual recovery

If a baseline is stale or missing:

1. Run the workflow on `main` with known-good code.
2. Confirm `assert-ai-artifacts/` includes `scores.jsonl`, `test_set.jsonl`, and `metrics.json`.
3. Upload or retain it as `assert-ai-baseline`.
4. Re-run the PR workflow.

## Version tags

Release tags use semantic versions such as `v1.0.0`. The release workflow force-updates the matching major tag, so `v1` points to the latest compatible `v1.x.y` release. Pin `@v1` for compatible fixes or an exact tag for maximum repeatability.
