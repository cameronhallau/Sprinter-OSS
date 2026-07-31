# Threat model

## Protected assets

- Detection evidence, prompts, model decisions, and audit history
- API, Splunk, ADX, Confluence, Teams, and model-provider credentials
- Pi OAuth state and the SQLite database
- Integrity of review results and evidence links

## Primary threats and controls

| Threat | Control |
| --- | --- |
| Stolen API token | SHA-256 token records, constant-time comparison, narrow scopes, rotation, local audit |
| Prompt injection in evidence | Untrusted-data instruction, no Pi tools/context/extensions, bounded evidence, strict output schema |
| Unsafe SIEM query | Explicit index/table allowlists and write-command rejection |
| Teams spoofing | Microsoft Agents SDK JWT validation, tenant allowlist, lifecycle-only processing |
| Unwanted Teams delivery | New destinations disabled until an administrator enables them |
| Process escape | Non-root container, read-only root, no capabilities, no-new-privileges, bounded resources |
| Secret disclosure | Secret files, restrictive modes, redaction, no credential values in readiness or logs |
| Lost or duplicated work | Durable queue, idempotency key, atomic claim, retries, restart recovery |
| Delivery outage | Durable per-target outbox with bounded exponential backoff |
| Dependency compromise | Locks, pinned Actions, SBOM, vulnerability scans, signed images and provenance |
| Evidence over-retention | Separate audit, evidence, job, and installation retention controls |

## Residual risks

SQLite cannot provide host-level HA. A compromised host can access mounted
credentials and data. Model output can still be wrong even when schema-valid,
so Teams notifications remain recommendations for analyst review. Operators
must constrain network egress and backend service accounts outside Sprinter.
