# Integration setup

All integrations are optional. Configure only the systems Sprinter needs, use a
dedicated identity for each one, and verify TLS with the operating system trust
store or a mounted private CA file.

## Splunk

Sprinter uses two independent Splunk paths:

- The management API runs bounded, read-only searches for review evidence and
  the scoped Splunk tool.
- HTTP Event Collector receives Sprinter audit events through the durable
  delivery outbox.

Create a search identity that can dispatch searches only over the required
indexes. Do not grant administrative, ingest, lookup-write, script, or saved
search management permissions. Create a separate HEC token restricted to the
intended audit index and source type.

```text
SPRINTER_SPLUNK_BASE_URL=https://splunk-api.example:8089
SPRINTER_SPLUNK_WEB_URL=https://splunk.example
SPRINTER_SPLUNK_USERNAME=sprinter-search
SPRINTER_SPLUNK_PASSWORD_FILE=/run/secrets/sprinter/splunk-password
SPRINTER_SPLUNK_ALLOWED_INDEXES=detection_results,endpoint,identity
SPRINTER_SPLUNK_RESULTS_INDEX=detection_results
SPRINTER_SPLUNK_HEC_URL=https://splunk-hec.example:8088/services/collector/event
SPRINTER_SPLUNK_HEC_TOKEN_FILE=/run/secrets/sprinter/splunk-hec-token
SPRINTER_SPLUNK_CA_FILE=/run/secrets/sprinter/organisation-ca.pem
```

`SPRINTER_SPLUNK_RESULTS_INDEX` is the one index Sprinter queries for `run`,
`result`, and `latest` review selectors. It must also appear in the allowlist.
`SPRINTER_SPLUNK_WEB_URL` creates analyst-facing evidence links. Omit the CA
setting when the endpoint has a certificate from the normal trusted chain.
TLS verification cannot be disabled.

The API rejects searches without an explicit allowed index and blocks
side-effecting commands. Sprinter audit events use source type
`sprinter:audit`.

## Azure Data Explorer

Register an application in Microsoft Entra ID, create a client credential, and
grant the service principal database viewer access only on the target Azure Data
Explorer database. Do not grant database ingestor, user, admin, or cluster-level
write roles.

```text
SPRINTER_ADX_CLUSTER_URL=https://cluster.region.kusto.windows.net
SPRINTER_ADX_DATABASE=Security
SPRINTER_ADX_TENANT_ID=00000000-0000-0000-0000-000000000000
SPRINTER_ADX_CLIENT_ID=00000000-0000-0000-0000-000000000000
SPRINTER_ADX_CLIENT_SECRET_FILE=/run/secrets/sprinter/adx-client-secret
SPRINTER_ADX_ALLOWED_TABLES=DeviceEvents,SigninLogs
```

The query endpoint accepts one read-only KQL statement that begins with an
allowlisted table, rejects management/write operations, and appends a row
limit. Azure Data Explorer is available to scoped API callers; a Seer detection
runner may execute feed KQL itself and supply the resulting evidence to
Sprinter.

## Confluence

Use a dedicated account or app credential that can read only the approved
spaces. Store its API token in a private file.

```text
SPRINTER_CONFLUENCE_BASE_URL=https://organisation.atlassian.net/wiki
SPRINTER_CONFLUENCE_EMAIL=sprinter-reader@example.com
SPRINTER_CONFLUENCE_API_TOKEN_FILE=/run/secrets/sprinter/confluence-token
SPRINTER_CONFLUENCE_ALLOWED_SPACES=SEC,IR
```

Sprinter adds the configured space allowlist to every content search. Do not use
an account with content creation or site administration rights.

## Microsoft Teams

Teams is a notification-only destination. Messages and commands are
authenticated, ignored, and never used to create jobs or conversational state.

1. Register a single-tenant application and bot in Microsoft Entra ID.
2. Create a client secret and save it as `secrets/teams-client-secret` with mode
   `0600`.
3. Set the bot messaging endpoint to
   `https://sprinter.example/api/v1/teams/events`.
4. Replace the placeholders in `teams/manifest.json`.
5. Supply a 192 by 192 pixel `color.png` and a transparent 32 by 32 pixel
   `outline.png`, then package the manifest and icons at the root of a ZIP file.
6. Upload the app to Teams and add it to each intended chat, team, or personal
   scope.

```text
SPRINTER_TEAMS_ENABLED=1
SPRINTER_TEAMS_APP_ID=00000000-0000-0000-0000-000000000000
SPRINTER_TEAMS_TENANT_ID=00000000-0000-0000-0000-000000000000
SPRINTER_TEAMS_CLIENT_SECRET_FILE=/run/secrets/sprinter/teams-client-secret
SPRINTER_TEAMS_ALLOWED_TENANT_IDS=00000000-0000-0000-0000-000000000000
SPRINTER_TEAMS_PUBLIC_BASE_URL=https://sprinter.example
```

An authenticated installation event creates an inactive destination. List
discovered destinations:

```console
curl --fail \
  -H "Authorization: Bearer $SPRINTER_OPERATOR_TOKEN" \
  https://sprinter.example/api/v1/teams/installations
```

Enable only a destination you recognize:

```console
curl --fail -X PATCH \
  -H "Authorization: Bearer $SPRINTER_OPERATOR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"enabled":true}' \
  https://sprinter.example/api/v1/teams/installations/INSTALLATION_ID
```

Sprinter fans each completed review out through a durable delivery record. One
destination failure does not erase or mark another destination's delivery as
failed. Uninstall lifecycle events deactivate the destination.

## Acceptance checks

For each enabled integration, test one allowed request, one denied request, a
backend timeout, and a certificate failure. Confirm secrets do not appear in
container logs, the local audit event exists before external delivery, and the
authenticated `/readyz` response reflects the expected state.
