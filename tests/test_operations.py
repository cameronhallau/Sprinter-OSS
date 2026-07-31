from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic import SecretStr
from sqlalchemy import select

from sprinter.backup import backup_database
from sprinter.models import AuditEvent, Outbox, new_id, utcnow
from sprinter.restore import restore_database


def test_verified_online_backup(container, tmp_path: Path) -> None:
    container.db.audit("backup.test", "tester", {"ok": True})
    destination = tmp_path / "backups" / "sprinter.db"
    digest = backup_database(container.settings.database_path, destination)
    assert len(digest) == 64
    assert destination.stat().st_mode & 0o777 == 0o600
    assert destination.with_suffix(".db.sha256").read_text().startswith(digest)
    with pytest.raises(FileExistsError):
        backup_database(container.settings.database_path, destination)
    restored = tmp_path / "restore" / "sprinter.db"
    restore_database(destination, destination.with_suffix(".db.sha256"), restored)
    assert restored.exists()
    assert restored.stat().st_mode & 0o777 == 0o600


def test_restore_rejects_bad_checksum(container, tmp_path: Path) -> None:
    backup = tmp_path / "backup.db"
    backup_database(container.settings.database_path, backup)
    checksum = backup.with_suffix(".db.sha256")
    checksum.write_text(f"{'0' * 64}  backup.db\n")
    with pytest.raises(ValueError, match="checksum"):
        restore_database(backup, checksum, tmp_path / "restored.db")


def test_retention_purges_expired_audit(container) -> None:
    event_id = new_id("audit")
    with container.db.session() as session:
        session.add(
            AuditEvent(
                id=event_id,
                event_type="expired",
                actor="tester",
                payload_json="{}",
                expires_at=utcnow() - timedelta(days=1),
            )
        )
    counts = container.db.purge()
    assert counts["audit_events"] == 1
    with container.db.session() as session:
        assert session.get(AuditEvent, event_id) is None


@pytest.mark.asyncio
async def test_audit_outbox_retries_delivery_failure(container) -> None:
    container.splunk.settings = container.settings.model_copy(
        update={
            "splunk_hec_url": "https://splunk.example/services/collector/event",
            "splunk_hec_token": SecretStr("token"),
        }
    )
    container.splunk.post_event = MagicMock(side_effect=RuntimeError("backend timeout"))
    container.audit("delivery.test", "tester", {"value": 1})
    result = await container.flush_outbox()
    assert result == {"sent": 0, "failed": 1}
    with container.db.session() as session:
        item = session.scalar(select(Outbox))
        assert item
        assert item.status == "retry"
        assert item.attempts == 1
        assert "backend timeout" in item.last_error
