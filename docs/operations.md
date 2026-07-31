# Operations

## Production prerequisites

- External HTTPS reverse proxy publishing only the API port
- Private Docker network and host firewall
- Mode `0600` secret files owned by the service operator
- Least-privilege service accounts and verified TLS for every backend
- Persistent `sprinter_data` and `pi_auth` volumes
- Tested backup destination outside the application host

Do not expose port 8080 directly to an untrusted network.

## Readiness

`GET /livez` confirms only that the API process can answer. Authenticated
`GET /readyz` returns `503` until the worker heartbeat is fresh, Pi's exact
version/model/authentication probe succeeds, and an enabled Teams destination
exists when Teams is enabled.

## Teams installation

Upload the notification-only manifest after replacing its placeholders. An
authenticated lifecycle event discovers the destination in a disabled state.
List it through `GET /api/v1/teams/installations`, then enable the intended
destination through its `PATCH` endpoint. Removing the app deactivates it.

## Backup

Pause neither API nor worker for an online SQLite backup:

```console
docker compose exec -T api python -m sprinter.backup /backup/sprinter.db
```

Store the backup and its checksum outside the host. Test restoration quarterly.

## Restore

Stop both services, preserve the failed volume, restore only a validated v1
backup into a fresh volume, set mode `0600`, and start the API before the
worker. Confirm `/readyz`, submit one canary review, and verify one Teams card.

```console
docker compose run --rm --no-deps api \
  python -m sprinter.restore /backup/sprinter.db /backup/sprinter.db.sha256
```

Legacy databases are intentionally rejected.

## Incident response

1. Disable external ingress and stop the worker if decision integrity is in doubt.
2. Preserve the database, container logs, image digest, SBOM, and relevant proxy logs.
3. Rotate affected API and backend credentials, including Pi OAuth state when applicable.
4. Determine affected job, evidence, decision, audit, and delivery IDs.
5. Rebuild from a signed image and restore a known-good database when required.
6. Document scope, timeline, corrective actions, and disclosure obligations.

Never delete audit data during active investigation.
