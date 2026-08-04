# Security policy

## Reporting a vulnerability

Please report suspected vulnerabilities privately by opening a GitHub security advisory for this repository or by contacting the maintainers through the repository owner.

Do not include secrets, provider keys, private prompts, model outputs, or customer data in public issues. Use placeholder names such as `AZURE_API_KEY`, `AZURE_API_BASE`, and `OPENAI_API_KEY`.

## Supported versions

Security fixes are applied to the latest `v1` release line. Pin `responsibleai/assert-ai-action@v1` for compatible fixes, or pin an exact release tag for repeatability.

## Trust model

This action is not a sandbox or security boundary. It runs the checked-out repository code with the credentials supplied to the workflow, and it uploads ASSERT artifacts that may include raw model inputs and outputs. Run it only on code and repositories that you trust with those credentials and artifacts.