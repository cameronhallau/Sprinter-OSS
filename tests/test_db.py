from __future__ import annotations

import sqlite3

import pytest
from sqlalchemy import inspect

from sprinter.db import Database, LegacyDatabaseError
from sprinter.models import JobStatus


def test_clean_schema_and_sqlite_hardening(settings) -> None:
    database = Database(settings)
    tables = set(inspect(database.engine).get_table_names())
    assert {
        "jobs",
        "evidence",
        "decisions",
        "findings",
        "audit_events",
        "delivery_outbox",
        "teams_installations",
        "worker_health",
        "retention_metadata",
        "alembic_version",
    } <= tables
    with database.engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA journal_mode").scalar_one().lower() == "wal"
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
        assert connection.exec_driver_sql("PRAGMA synchronous").scalar_one() == 2
    assert settings.database_path.stat().st_mode & 0o777 == 0o600


def test_legacy_database_is_rejected(settings) -> None:
    with sqlite3.connect(settings.database_path) as connection:
        connection.execute("create table drafts (id text primary key)")
    with pytest.raises(LegacyDatabaseError, match="fresh data volume"):
        Database(settings)


def test_job_idempotency_and_recovery(container) -> None:
    first, created = container.db.create_job(
        idempotency_key="runner-run-001",
        selector_type="run",
        selector={"type": "run", "run_id": "001"},
        source="runner",
        summary={},
        row_limit=10,
    )
    replay, replay_created = container.db.create_job(
        idempotency_key="runner-run-001",
        selector_type="run",
        selector={"type": "run", "run_id": "001"},
        source="runner",
        summary={},
        row_limit=10,
    )
    assert created is True
    assert replay_created is False
    assert replay.id == first.id
    claimed = container.db.claim_job()
    assert claimed and claimed.status == JobStatus.running.value


def test_audit_is_local_before_delivery(container) -> None:
    event_id = container.audit("test.event", "tester", {"password": "never-store-me"})
    with container.db.engine.connect() as connection:
        payload = connection.exec_driver_sql(
            "select payload_json from audit_events where id = ?", (event_id,)
        ).scalar_one()
    assert "never-store-me" not in payload
    assert "[REDACTED]" in payload
