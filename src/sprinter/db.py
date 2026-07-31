from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import Engine, create_engine, event, inspect, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from sprinter.config import Settings
from sprinter.models import (
    AuditEvent,
    Decision,
    Evidence,
    Finding,
    Job,
    JobStatus,
    Outbox,
    RetentionMetadata,
    TeamsInstallation,
    WorkerHealth,
    new_id,
    utcnow,
)

sqlite3.register_adapter(datetime, lambda value: value.isoformat())
sqlite3.register_converter("datetime", lambda value: datetime.fromisoformat(value.decode("utf-8")))


class LegacyDatabaseError(RuntimeError):
    pass


class IdempotencyConflict(RuntimeError):
    pass


def dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


class Database:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.path = settings.database_path
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._reject_legacy_database()
        self.engine = self._create_engine()
        self._migrate()
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)

    def _reject_legacy_database(self) -> None:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return
        try:
            with sqlite3.connect(self.path) as connection:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "select name from sqlite_master where type='table' and name not like 'sqlite_%'"
                    )
                }
        except sqlite3.DatabaseError as exc:
            raise LegacyDatabaseError("database is not a valid Sprinter v1 SQLite file") from exc
        if tables and "alembic_version" not in tables:
            raise LegacyDatabaseError("legacy database detected; Sprinter v1 requires a fresh data volume")

    def _create_engine(self) -> Engine:
        engine = create_engine(
            f"sqlite:///{self.path}",
            connect_args={"check_same_thread": False, "timeout": 30},
            pool_pre_ping=True,
        )

        @event.listens_for(engine, "connect")
        def configure_sqlite(dbapi_connection: sqlite3.Connection, _record: object) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA synchronous=FULL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

        return engine

    def _migrate(self) -> None:
        config = AlembicConfig()
        config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
        config.set_main_option("sqlalchemy.url", f"sqlite:///{self.path}")
        command.upgrade(config, "head")
        os.chmod(self.path, 0o600)

    @contextmanager
    def session(self) -> Iterator[Session]:
        with self.sessions() as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    def audit(self, event_type: str, actor: str, payload: dict[str, Any]) -> str:
        event_id = new_id("audit")
        with self.session() as session:
            session.add(
                AuditEvent(
                    id=event_id,
                    event_type=event_type,
                    actor=actor[:128],
                    payload_json=dumps(payload),
                    expires_at=utcnow() + timedelta(days=self.settings.audit_retention_days),
                )
            )
        return event_id

    def create_job(
        self,
        *,
        idempotency_key: str,
        selector_type: str,
        selector: dict[str, Any],
        source: str,
        summary: dict[str, Any],
        row_limit: int,
    ) -> tuple[Job, bool]:
        with self.session() as session:
            existing = session.scalar(select(Job).where(Job.idempotency_key == idempotency_key))
            if existing:
                expected = (
                    selector_type,
                    dumps(selector),
                    source[:128],
                    dumps(summary),
                    row_limit,
                )
                actual = (
                    existing.selector_type,
                    existing.selector_json,
                    existing.source,
                    existing.summary_json,
                    existing.row_limit,
                )
                if actual != expected:
                    raise IdempotencyConflict("idempotency key was already used for a different request")
                return existing, False
            job = Job(
                id=new_id("job"),
                idempotency_key=idempotency_key,
                selector_type=selector_type,
                selector_json=dumps(selector),
                source=source[:128],
                summary_json=dumps(summary),
                row_limit=row_limit,
                max_attempts=self.settings.job_max_attempts,
            )
            session.add(job)
            try:
                session.flush()
            except IntegrityError:
                session.rollback()
                existing = session.scalar(select(Job).where(Job.idempotency_key == idempotency_key))
                if existing:
                    return existing, False
                raise
            return job, True

    def get_job(self, job_id: str) -> Job | None:
        with self.session() as session:
            return session.get(Job, job_id)

    def claim_job(self) -> Job | None:
        now = utcnow()
        with self.session() as session:
            candidate = session.scalar(
                select(Job)
                .where(
                    Job.status.in_([JobStatus.pending.value, JobStatus.retry.value]),
                    Job.available_at <= now,
                )
                .order_by(Job.created_at)
                .limit(1)
            )
            if not candidate:
                return None
            changed = session.execute(
                update(Job)
                .where(
                    Job.id == candidate.id,
                    Job.status.in_([JobStatus.pending.value, JobStatus.retry.value]),
                )
                .values(
                    status=JobStatus.running.value,
                    attempts=Job.attempts + 1,
                    claimed_at=now,
                    updated_at=now,
                )
            )
            if getattr(changed, "rowcount", 0) != 1:
                return None
            session.flush()
            return session.get(Job, candidate.id)

    def recover_abandoned_jobs(self, older_than_seconds: int = 900) -> int:
        cutoff = utcnow() - timedelta(seconds=older_than_seconds)
        with self.session() as session:
            result = session.execute(
                update(Job)
                .where(Job.status == JobStatus.running.value, Job.claimed_at < cutoff)
                .values(status=JobStatus.retry.value, available_at=utcnow(), updated_at=utcnow())
            )
            return int(getattr(result, "rowcount", 0) or 0)

    def retry_job(self, job: Job, error: dict[str, Any], delay_seconds: int) -> None:
        terminal = job.attempts >= job.max_attempts
        with self.session() as session:
            session.execute(
                update(Job)
                .where(Job.id == job.id)
                .values(
                    status=JobStatus.failed.value if terminal else JobStatus.retry.value,
                    error_json=dumps(error),
                    available_at=utcnow() + timedelta(seconds=delay_seconds),
                    completed_at=utcnow() if terminal else None,
                    updated_at=utcnow(),
                )
            )

    def complete_job(
        self,
        job: Job,
        decision: dict[str, Any],
        evidence: list[dict[str, Any]],
        model: dict[str, str],
    ) -> str:
        decision_id = new_id("decision")
        now = utcnow()
        with self.session() as session:
            for item in evidence:
                session.add(
                    Evidence(
                        id=new_id("evidence"),
                        job_id=job.id,
                        kind=str(item.get("kind") or "event")[:32],
                        title=str(item.get("title") or "Evidence")[:256],
                        uri=str(item.get("uri") or ""),
                        payload_json=dumps(item.get("payload") or {}),
                        expires_at=now + timedelta(days=self.settings.evidence_retention_days),
                    )
                )
            session.add(
                Decision(
                    id=decision_id,
                    job_id=job.id,
                    verdict=decision["verdict"],
                    severity=decision["severity"],
                    summary=decision["summary"],
                    rationale_json=dumps(
                        {
                            "rationale": decision["rationale"],
                            "recommended_actions": decision["recommended_actions"],
                            "evidence_ids": decision["evidence_ids"],
                        }
                    ),
                    model_provider=model["provider"],
                    model_id=model["model"],
                    pi_version=model["pi_version"],
                )
            )
            dedupe_key = decision["finding_key"]
            existing = session.scalar(select(Finding).where(Finding.dedupe_key == dedupe_key))
            if existing:
                existing.occurrences += 1
                existing.last_seen_at = now
                existing.decision_id = decision_id
            else:
                session.add(
                    Finding(
                        id=new_id("finding"),
                        dedupe_key=dedupe_key,
                        decision_id=decision_id,
                    )
                )
            result = {**decision, "decision_id": decision_id}
            session.execute(
                update(Job)
                .where(Job.id == job.id)
                .values(
                    status=JobStatus.succeeded.value,
                    result_json=dumps(result),
                    error_json=None,
                    completed_at=now,
                    updated_at=now,
                )
            )
        return decision_id

    def enqueue(self, channel: str, payload: dict[str, Any], target_id: str = "") -> str:
        outbox_id = new_id("delivery")
        with self.session() as session:
            session.add(
                Outbox(
                    id=outbox_id,
                    channel=channel,
                    target_id=target_id,
                    payload_json=dumps(payload),
                )
            )
        return outbox_id

    def pending_deliveries(self, limit: int = 25) -> list[Outbox]:
        with self.session() as session:
            return list(
                session.scalars(
                    select(Outbox)
                    .where(Outbox.status.in_(["pending", "retry"]), Outbox.available_at <= utcnow())
                    .order_by(Outbox.created_at)
                    .limit(limit)
                )
            )

    def delivery_succeeded(self, outbox_id: str) -> None:
        with self.session() as session:
            session.execute(
                update(Outbox)
                .where(Outbox.id == outbox_id)
                .values(status="sent", attempts=Outbox.attempts + 1, last_error="", updated_at=utcnow())
            )

    def delivery_failed(self, item: Outbox, error: str) -> None:
        attempts = item.attempts + 1
        terminal = attempts >= item.max_attempts
        delay = min(3600, 2 ** min(attempts, 10))
        with self.session() as session:
            session.execute(
                update(Outbox)
                .where(Outbox.id == item.id)
                .values(
                    status="failed" if terminal else "retry",
                    attempts=attempts,
                    last_error=error[:4000],
                    available_at=utcnow() + timedelta(seconds=delay),
                    updated_at=utcnow(),
                )
            )

    def upsert_installation(self, activity: Any, tenant_id: str) -> TeamsInstallation:
        reference = activity.get_conversation_reference()
        reference_json = reference.model_dump_json(by_alias=True, exclude_none=True)
        conversation_id = activity.conversation.id
        scope = str(activity.conversation.conversation_type or "personal")
        with self.session() as session:
            installation = session.scalar(
                select(TeamsInstallation).where(
                    TeamsInstallation.tenant_id == tenant_id,
                    TeamsInstallation.conversation_id == conversation_id,
                )
            )
            if not installation:
                installation = TeamsInstallation(
                    id=new_id("teams"),
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    service_url=activity.service_url,
                    scope=scope,
                    reference_json=reference_json,
                    enabled=False,
                    active=True,
                )
                session.add(installation)
            else:
                installation.service_url = activity.service_url
                installation.scope = scope
                installation.reference_json = reference_json
                installation.active = True
                installation.last_seen_at = utcnow()
            session.flush()
            return installation

    def deactivate_installation(self, tenant_id: str, conversation_id: str) -> bool:
        with self.session() as session:
            result = session.execute(
                update(TeamsInstallation)
                .where(
                    TeamsInstallation.tenant_id == tenant_id,
                    TeamsInstallation.conversation_id == conversation_id,
                )
                .values(active=False, enabled=False, last_seen_at=utcnow())
            )
            return bool(getattr(result, "rowcount", 0))

    def installations(self, enabled_only: bool = False) -> list[TeamsInstallation]:
        with self.session() as session:
            query = select(TeamsInstallation).order_by(TeamsInstallation.discovered_at)
            if enabled_only:
                query = query.where(TeamsInstallation.enabled.is_(True), TeamsInstallation.active.is_(True))
            return list(session.scalars(query))

    def set_installation_enabled(self, installation_id: str, enabled: bool) -> TeamsInstallation | None:
        with self.session() as session:
            installation = session.get(TeamsInstallation, installation_id)
            if not installation or (enabled and not installation.active):
                return None
            installation.enabled = enabled
            installation.last_seen_at = utcnow()
            session.flush()
            return installation

    def heartbeat(self, pi_ready: bool, pi_error: str = "", details: dict[str, Any] | None = None) -> None:
        with self.session() as session:
            health = session.get(WorkerHealth, "worker")
            if not health:
                health = WorkerHealth(role="worker", heartbeat_at=utcnow())
                session.add(health)
            health.heartbeat_at = utcnow()
            health.pi_ready = pi_ready
            health.pi_checked_at = utcnow()
            health.pi_error = pi_error[:4000]
            health.details_json = dumps(details or {})

    def readiness(self) -> dict[str, Any]:
        with self.session() as session:
            worker = session.get(WorkerHealth, "worker")
            enabled_targets = session.scalar(
                select(text("count(*)")).select_from(TeamsInstallation).where(
                    TeamsInstallation.enabled.is_(True), TeamsInstallation.active.is_(True)
                )
            )
            return {
                "database": True,
                "worker_heartbeat": worker.heartbeat_at.isoformat() if worker else None,
                "worker_fresh": bool(
                    worker
                    and worker.heartbeat_at
                    >= utcnow() - timedelta(seconds=self.settings.worker_stale_seconds)
                ),
                "pi_ready": bool(worker and worker.pi_ready),
                "pi_error": worker.pi_error if worker else "worker has not reported",
                "enabled_teams_destinations": int(enabled_targets or 0),
            }

    def purge(self) -> dict[str, int]:
        now = utcnow()
        counts: dict[str, int] = {}
        with self.session() as session:
            for name, statement in (
                ("evidence", text("delete from evidence where expires_at < :now")),
                ("audit_events", text("delete from audit_events where expires_at < :now")),
                (
                    "jobs",
                    text(
                        "delete from jobs where status in ('succeeded','failed') "
                        "and completed_at < :job_cutoff"
                    ),
                ),
                (
                    "teams_installations",
                    text(
                        "delete from teams_installations where active = 0 "
                        "and last_seen_at < :teams_cutoff"
                    ),
                ),
                (
                    "delivery_outbox",
                    text(
                        "delete from delivery_outbox "
                        "where status in ('sent','failed') and updated_at < :audit_cutoff"
                    ),
                ),
            ):
                result = session.execute(
                    statement,
                    {
                        "now": now,
                        "job_cutoff": now - timedelta(days=self.settings.job_retention_days),
                        "teams_cutoff": now - timedelta(days=self.settings.teams_installation_retention_days),
                        "audit_cutoff": now - timedelta(days=self.settings.audit_retention_days),
                    },
                )
                counts[name] = int(getattr(result, "rowcount", 0) or 0)
            metadata = session.get(RetentionMetadata, "daily")
            if not metadata:
                metadata = RetentionMetadata(key="daily")
                session.add(metadata)
            metadata.last_run_at = now
            metadata.details_json = dumps(counts)
        return counts

    def schema_revision(self) -> str:
        if not inspect(self.engine).get_table_names():
            return ""
        with self.engine.connect() as connection:
            return str(connection.execute(text("select version_num from alembic_version")).scalar_one())
