from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError

from sprinter.config import Settings, parse_token_records


def test_token_records_are_strict() -> None:
    digest = hashlib.sha256(b"token").hexdigest()
    record = parse_token_records(f"operator:{digest}:jobs:read,tools:splunk")[0]
    assert record.name == "operator"
    assert record.scopes == {"jobs:read", "tools:splunk"}

    with pytest.raises(ValueError, match="SHA-256"):
        parse_token_records("operator:not-a-digest:admin")
    with pytest.raises(ValueError, match="placeholder"):
        parse_token_records(f"operator:{'0' * 64}:admin")
    with pytest.raises(ValueError, match="unknown scopes"):
        parse_token_records(f"operator:{digest}:root")


def test_legacy_environment_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANALYST_API_TOKEN", "legacy")
    with pytest.raises(ValidationError, match=r"legacy ANALYST_\*"):
        Settings(pi_provider="openrouter", pi_model="test/model")


def test_runtime_requires_pi_policy_and_auth(tmp_path) -> None:
    settings = Settings(
        environment="development",
        database_path=tmp_path / "sprinter.db",
        pi_provider="openrouter",
        pi_model="test/model",
    )
    with pytest.raises(ValueError, match="API_TOKEN_RECORDS"):
        settings.validate_runtime("api")


def test_secret_file_must_be_private(settings: Settings, tmp_path) -> None:
    secret = tmp_path / "splunk.secret"
    secret.write_text("secret")
    secret.chmod(0o644)
    unsafe = settings.model_copy(
        update={
            "splunk_base_url": "https://splunk.example",
            "splunk_username": "svc",
            "splunk_password_file": secret,
            "splunk_allowed_indexes": "security",
        }
    )
    with pytest.raises(ValueError, match="private readable file"):
        unsafe.validate_runtime("api")
