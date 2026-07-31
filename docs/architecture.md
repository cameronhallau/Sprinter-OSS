# Architecture

## Trust boundaries

Sprinter has two processes built from one image:

- The API validates scoped credentials, request size, rate limits, schemas, and
  read-only tool policies before writing durable jobs.
- The worker is the only process allowed to invoke Pi or deliver outbox items.

Both processes share one SQLite volume. SQLite uses WAL, foreign keys,
`synchronous=FULL`, a 30-second busy timeout, and bounded transactions. This
shape supports one host and one active worker; it is not a distributed queue or
an HA database.

## Review flow

1. A runner submits a selector and idempotency key to `/api/v1/review-jobs`.
2. The API writes a pending job and a local audit event in one trusted store.
3. The worker claims one job and collects bounded evidence from an allowlisted
   backend or from the runner's supplied summary.
4. Sprinter redacts configured keys and marks all evidence as untrusted data.
5. Pi runs as a new isolated JSONL RPC process with sessions, tools, extensions,
   skills, templates, and context files disabled.
6. Sprinter validates the model response against a strict schema. One
   schema-correction attempt is allowed.
7. Evidence, decision, model identity, Pi version, and finding deduplication are
   committed before notification delivery is queued.
8. Each enabled Teams destination receives its own outbox item.

Pi unavailability pauses reviews. Sprinter does not substitute a deterministic
verdict and never triggers a remediation action.

## Public interfaces

`/livez` is intentionally minimal and public. `/readyz` requires `admin` and
checks the database, worker heartbeat, Pi probe, and Teams destination state.
All product APIs are under `/api/v1`; unversioned and legacy routes do not exist.

Teams is one-way. The Microsoft 365 Agents SDK validates signed activities.
Only installation and conversation lifecycle metadata is retained. Message
activities are acknowledged and audited as ignored, without storing text.
