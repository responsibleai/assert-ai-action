# Contributing

Thanks for improving the ASSERT safety regression gate.

## Development setup

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
python -m pytest tests/ -q
python scripts/check_bundle.py
python scripts/check_onboard_urls.py
```

## Pull request checklist

- Keep the action customer-safe: do not commit secrets, `.env` files, generated artifacts, traces, logs, or provider outputs.
- Update `README.md`, `ONBOARD.md`, or `docs/` when changing inputs, outputs, gate semantics, or onboarding behavior.
- Keep workflow snippets pinned to a major version such as `actions/checkout@v4` or `responsibleai/assert-ai-action@v1`.
- Run the helper tests above before requesting review.