from __future__ import annotations

import pytest
from pydantic import ValidationError

from sprinter.config import Settings, make_token_verifier, parse_token_records, verify_token


def test_token_records_are_strict() -> None:
    verifier = make_token_verifier("token", b"\x02" * 16)
    record = parse_token_records(f"operator:{verifier}:jobs:read,tools:splunk")[0]
    assert record.name == "operator"
    assert record.scopes == {"jobs:read", "tools:splunk"}
    assert verify_token("token", record.verifier)
    assert not verify_token("wrong", record.verifier)

    with pytest.raises(ValueError, match="scrypt verifier"):
        parse_token_records("operator:not-a-verifier:admin")
    with pytest.raises(ValueError, match="unknown scopes"):
        parse_token_records(f"operator:{verifier}:root")


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
            "splunk_results_index": "security",
        }
    )
    with pytest.raises(ValueError, match="private readable file"):
        unsafe.validate_runtime("api")


def test_splunk_results_index_must_be_explicit_and_allowlisted(settings: Settings, tmp_path) -> None:
    secret = tmp_path / "splunk.secret"
    secret.write_text("secret")
    secret.chmod(0o600)
    configured = settings.model_copy(
        update={
            "splunk_base_url": "https://splunk.example",
            "splunk_username": "svc",
            "splunk_password_file": secret,
            "splunk_allowed_indexes": "security,detection_results",
        }
    )
    with pytest.raises(ValueError, match="SPRINTER_SPLUNK_RESULTS_INDEX is required"):
        configured.validate_runtime("api")

    configured = configured.model_copy(update={"splunk_results_index": "other"})
    with pytest.raises(ValueError, match="must be included"):
        configured.validate_runtime("api")

    configured.model_copy(update={"splunk_results_index": "detection_results"}).validate_runtime("api")
