# Seer STIX feed

## Responsibility boundary

Seer publishes threat intelligence. A deterministic detection runner consumes
that feed and executes suitable artifacts. Sprinter reviews the resulting hits
with Pi, records the decision, and sends one-way Teams notifications.

Sprinter does not poll STIX, execute arbitrary feed content, or decide whether a
detection is compatible with available telemetry. Keeping execution outside the
review service makes the runner independently testable and preserves
least-privilege boundaries.

```text
Seer STIX 2.1 collection
        |
        v
deterministic runner and execution ledger
        |
        +--> Splunk / Azure Data Explorer / approved YARA engine
        |
        v
normalized run summary and evidence
        |
        v
POST /api/v1/review-jobs
        |
        v
Pi review -> durable decision -> Teams card
```

## Feed contract

Configure the runner to poll Seer's authenticated STIX 2.1 collection endpoint:

```text
https://SEER_HOST/stix/collections/osint-bot/objects
```

Store the Seer credential in a private file and verify the server certificate.
Use STIX pagination and persist the returned cursor or modification watermark.
Do not place a bearer token in a URL or command-line argument.

The current Seer collection may contain:

- Native STIX `indicator` objects with `pattern` and `pattern_type`
- Strict related IOC values in `x_related_iocs`
- `x-detection-analytic` objects with a query language and query body
- Detection entries in `x_publication_payload.detections`
- KQL, Sigma, or YARA fenced blocks in a publication body

The runner must reject malformed artifacts and preserve their STIX object ID,
version, source, and marking metadata in its local audit record.

## Execute-once identity

Scheduled runs execute only content that is newly ingested. A later poll must
not rerun the full feed.

- IOC identity is SHA-256 over `ioc`, a null byte, and the normalized
  case-insensitive value.
- Detection identity is SHA-256 over the normalized language bucket, a null
  byte, and the normalized rule or query body.
- Native STIX indicator identity also accounts for canonical `pattern` and
  `pattern_type`.
- A changed rule body is new content and executes once.
- Metadata-only publication changes do not replay unchanged content.
- Mark an identity complete only after its execution outcome and evidence are
  committed atomically.

Use a durable ledger with separate `pending`, `running`, `completed`, and
`failed` states. On restart, recover stale `running` entries. A manually
authorized replay must identify exact artifact IDs and be audited; never make
full-feed replay part of the schedule.

## Execution routing

| Artifact | Deterministic destination | Required outcome |
| --- | --- | --- |
| IOC | Approved Splunk or telemetry indexes | Match rows or explicit successful zero-match result |
| Sigma | Convert with the pinned backend, validate indexes, run read-only SPL | Conversion, query, matches, and evidence link |
| KQL | Azure Data Explorer only when table/schema preflight passes | Matches or an explicit environment gap |
| YARA | Approved file or endpoint scanning engine | Match rows or an explicit engine/coverage gap |

An incompatible table, unavailable engine, missing telemetry, timeout, or query
error is an `environment_gap` or `run_failed` outcome. It is not evidence of
zero malicious activity.

## Result event

Write each deterministic result to the index configured as
`SPRINTER_SPLUNK_RESULTS_INDEX`, or supply it directly in the review request.
Every result should include:

```json
{
  "run_id": "20260731T010203Z-7f63b1",
  "workflow": "stix_ingest",
  "result_id": "result-unique-within-source",
  "status": "matched",
  "artifact_id": "sha256-identity",
  "stix_object_id": "indicator--example",
  "detection_id": "stable-rule-id",
  "detection_name": "Example detection",
  "source_type": "ioc",
  "severity": "high",
  "indicator_value": "example.invalid",
  "host": "endpoint-01",
  "evidence_url": "https://evidence.example/search/result",
  "match_count": 1
}
```

Use `status` values such as `matched`, `no_match`, `environment_gap`, and
`run_failed`. Keep stable detection and entity fields separate from timestamps
so Sprinter can deduplicate findings across runs.

## Submit the run

Create a Sprinter API token with `reviews:write` and store it in a mode `0600`
file. After the runner commits its ledger and result events, create a bounded
summary JSON file:

```json
{
  "run_id": "20260731T010203Z-7f63b1",
  "workflow": "stix_ingest",
  "feed_updates": 1,
  "new_content": {
    "ioc": 4,
    "kql": 1,
    "sigma": 1,
    "yara": 0
  },
  "attempted": {
    "ioc": 4,
    "kql": 1,
    "sigma": 1,
    "yara": 0
  },
  "raw_matches": 2,
  "new_deduplicated_matches": 1,
  "execution_issues": []
}
```

Submit it with the included helper:

```console
python scripts/submit_seer_run.py \
  --sprinter-url https://sprinter.example \
  --token-file /run/secrets/seer/sprinter-review-token \
  --summary-file /var/lib/seer/runs/20260731T010203Z-7f63b1.json
```

The helper verifies TLS, rejects redirects, limits the summary to 1 MiB, and
uses `seer:osint-bot:RUN_ID` as the default idempotency key. Repeating the same
submission returns the same durable job. Reusing that key with different
content returns `409`.

When Splunk is configured, Sprinter looks up rows with the matching `run_id` and
`workflow` in `SPRINTER_SPLUNK_RESULTS_INDEX`. Without Splunk, or when evidence
lives elsewhere, add a bounded `evidence` array to the summary:

```json
{
  "evidence": [
    {
      "kind": "adx",
      "title": "Encoded PowerShell behavior",
      "uri": "https://evidence.example/query/123",
      "payload": {
        "detection_id": "rule-123",
        "host": "endpoint-01",
        "severity": "high",
        "match_count": 1
      }
    }
  ]
}
```

Do not include credentials, raw Teams messages, unrestricted event dumps, or
more rows than an analyst needs to verify the decision.

## End-to-end acceptance

1. Publish one new, non-production test artifact in Seer.
2. Confirm the runner records one eligible identity and executes it once.
3. Confirm the normalized result contains the run and evidence fields.
4. Submit the run and observe a `202` response.
5. Confirm the Sprinter job succeeds and its evidence IDs are valid.
6. Confirm each enabled Teams destination receives one concise card with
   collapsed run details and evidence links at the bottom.
7. Poll Seer again and confirm the unchanged artifact is not executed or
   submitted as new work.
