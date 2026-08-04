# Release procedure

Use immutable semantic release tags such as `v1.0.1`, plus a floating major tag (`v1`) for compatible fixes. The exact semver tag is the release anchor; the floating major tag is only the convenience pointer.

## Cut a release

```powershell
git fetch live --tags --force
git checkout main
git pull --ff-only live main
python scripts/check_bundle.py
python scripts/check_onboard_urls.py
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
python -m pytest tests/ -q
```

Before tagging, bump `scripts/_version.py` to the version you are about to cut.
That constant is stamped into every `gate_report.json` as `action_version`, so
if it lags, customer bug reports cite a release that was never published.
`tests/test_action_version.py` fails when it does not match the newest tag.

Pick the next semver tag, then publish in this order:

```powershell
$version = "v1.0.1"
$major = "v1"

# 1. Create and push the immutable semver tag.
git tag $version
git push live $version

# 2. Move the floating major tag to the same commit.
git tag -f $major $version
git push live $major --force

# 3. Create the GitHub Release from the exact semver tag, not from `v1`.
gh release create $version --repo responsibleai/assert-ai-action --title "ASSERT safety regression gate $version" --notes-file release-notes.md
```

The release workflow also moves the matching major tag when a semver tag is pushed. The explicit `git tag -f` step above is still documented so maintainers know the invariant and can repair it manually if automation is disabled or fails.

## Verify tags and release

```powershell
git fetch live --tags --force
git rev-parse v1
git rev-parse v1.0.1
gh release view v1.0.1 --repo responsibleai/assert-ai-action --json tagName,isDraft,isPrerelease,url
```

`v1` and the latest compatible `v1.x.y` tag must resolve to the same hash. Older exact tags such as `v1.0.0` must remain on their original release commits.

## Do not

- Do not move an exact release tag after publishing it, except to repair an accidental move back to its original release commit.
- Do not create a Release from the floating `v1` tag.
- Do not publish a release before the action helper tests pass.
- Do not include private prompts, provider outputs, secrets, or `.env` values in release notes.