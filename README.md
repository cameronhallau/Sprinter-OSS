# Sprinter

Sprinter reviews deterministic security detection results with
[Pi](https://github.com/earendil-works/pi), records the evidence and decision
durably, and sends concise notification-only Adaptive Cards to Microsoft Teams.

Sprinter does not execute remediation actions and does not accept analyst
commands through Teams. It is designed for a hardened, single-node deployment;
the SQLite architecture is deliberately non-HA.

## Architecture

The API accepts authenticated review jobs and bounded tool requests. A separate
worker claims jobs from SQLite, collects evidence, invokes an isolated Pi RPC
process, validates the result schema, records the decision, and delivers
notifications through a durable outbox.

Only `/livez` is public. `/readyz` and all `/api/v1` routes require scoped bearer
tokens. The API must be published through an external HTTPS reverse proxy.

## Quick start

1. Copy `.env.example` to `.env` and replace every placeholder.
2. Create secret files outside the repository with mode `0600`.
3. Authenticate Pi against the persistent `pi_auth` volume:

   ```console
   docker compose run --rm --entrypoint pi worker
   ```

4. Start the API and worker:

   ```console
   docker compose up --build -d
   ```

5. Check liveness at `http://127.0.0.1:8080/livez`.

Continue with the [initial setup guide](docs/setup.md), then configure
[Splunk, Azure Data Explorer, Confluence, and Teams](docs/integrations.md).
The [Seer STIX guide](docs/seer-stix.md) defines the deterministic feed and
review handoff. See [operations](docs/operations.md),
[architecture](docs/architecture.md), and the
[threat model](docs/threat-model.md) before a production deployment.

## Review API

Submit a durable review:

```console
curl -X POST http://127.0.0.1:8080/api/v1/review-jobs \
  -H "Authorization: Bearer $SPRINTER_TOKEN" \
  -H "Idempotency-Key: source-run-20260731" \
  -H "Content-Type: application/json" \
  -d '{"selector":{"type":"run","run_id":"run-123"},"source":"stix-runner"}'
```

The response contains a job URL. No legacy endpoints or `ANALYST_*`
configuration names are supported.

## Development

Use Python 3.12 and the committed lock:

```console
uv sync --all-extras
uv run pytest
uv run ruff check .
uv run mypy
```

## Security

Do not report vulnerabilities in public issues. Follow
[SECURITY.md](SECURITY.md) for private disclosure instructions.
