# Initial setup

This guide creates a new single-node Sprinter deployment. Sprinter v1 requires a
fresh data volume and intentionally does not import earlier databases or
configuration names.

## 1. Prepare the host

Install Docker Engine with the Compose plugin. Provide an HTTPS reverse proxy
and a DNS name before enabling Teams. Keep TCP port 8080 bound to loopback; the
provided Compose file already publishes it as `127.0.0.1:8080`.

Create a private secrets directory:

```console
mkdir -m 0700 secrets
```

The Compose file mounts this directory read-only at `/run/secrets/sprinter` in
both containers. Set `SPRINTER_SECRETS_DIR` to an absolute host path if the
directory is not beside the Compose file. Never commit this directory.

## 2. Create an API credential

Generate a random token and store it for clients that submit or inspect jobs:

```console
openssl rand -hex 32 > secrets/operator-token
chmod 0600 secrets/operator-token
python scripts/hash_token.py
```

Enter the generated token when prompted. Put only the resulting salted scrypt
verifier in `SPRINTER_API_TOKEN_RECORDS`; the clear token remains outside
configuration.

Use separate credentials for separate callers. A Seer runner normally needs
`reviews:write,jobs:read`. An operator credential can have `admin`. Available
scopes are:

- `reviews:write`
- `jobs:read`
- `tools:splunk`
- `tools:adx`
- `tools:confluence`
- `tools:sigma`
- `teams:admin`
- `admin`

The record format is:

```text
name:scrypt-verifier:scope,scope;another-name:scrypt-verifier:scope
```

## 3. Configure Sprinter

Copy `.env.example` to `.env`. Set a real Pi provider and model, acknowledge the
applicable provider data policy, and replace the token placeholder. Configuration
uses only `SPRINTER_*` names.

Secret values for Splunk, Azure Data Explorer, Confluence, and Teams belong in
mode `0600` files under `secrets/`. Their environment settings must refer to the
container paths, for example:

```text
SPRINTER_SPLUNK_PASSWORD_FILE=/run/secrets/sprinter/splunk-password
```

Leave an optional integration's URL empty to disable it. Complete
[integration setup](integrations.md) before setting its URL.

## 4. Authenticate Pi

Sprinter uses the Pi runtime for provider authentication and model selection.
Authenticate once against the same persistent `pi_auth` volume used by the
worker:

```console
docker compose run --rm --entrypoint pi worker
```

Complete the provider login or configure the provider credential using Pi's
supported flow. Do not put provider credentials in Sprinter's database. The
worker verifies Pi `0.83.0`, the configured provider/model, authentication, and
a bounded smoke request before it reports healthy.

## 5. Start and verify

```console
docker compose up --build -d
curl --fail http://127.0.0.1:8080/livez
curl --fail \
  -H "Authorization: Bearer $(cat secrets/operator-token)" \
  http://127.0.0.1:8080/readyz
```

`/livez` proves only that the API process responds. `/readyz` also requires a
fresh worker heartbeat and a working Pi probe. When Teams is enabled, readiness
also requires at least one enabled Teams destination.

## 6. Publish HTTPS

Terminate TLS at a maintained reverse proxy and forward to
`http://127.0.0.1:8080`. Preserve the `Authorization` header, set a request-body
limit no larger than `SPRINTER_MAX_BODY_BYTES`, add proxy-side rate limiting,
and record request IDs without recording bearer tokens or bodies.

Only `/livez` is intentionally unauthenticated. The Teams callback
`/api/v1/teams/events` is authenticated by Microsoft activity tokens. Every
other route requires a scoped Sprinter bearer token.

After setup, test backup and restore using [operations.md](operations.md), then
submit a canary review before connecting a production feed.
