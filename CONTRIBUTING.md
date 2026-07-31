# Contributing

Contributions require a focused issue or pull request, passing tests, and no
secrets or customer data. Use Python 3.12 and the committed `uv.lock`.

Before opening a pull request, run:

```console
uv run ruff check .
uv run mypy
uv run pytest
uv run bandit -c pyproject.toml -r src
uv run pip-audit --ignore-vuln PYSEC-2026-2447
npm audit --omit=dev
```

Security-sensitive changes must include negative tests and an update to the
threat model when trust boundaries change. By contributing, you agree that your
work is licensed under the MIT licence.

The single documented audit exception is reviewed in
`docs/security-exceptions.md`; do not add an exception without a threat
analysis, owner, expiry condition, and compensating controls.
