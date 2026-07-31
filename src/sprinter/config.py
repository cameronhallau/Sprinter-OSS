from __future__ import annotations

import hashlib
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PI_VERSION = "0.83.0"
TOKEN_DIGEST = re.compile(r"^[0-9a-f]{64}$")
ALL_SCOPES = frozenset(
    {
        "reviews:write",
        "jobs:read",
        "tools:splunk",
        "tools:adx",
        "tools:confluence",
        "tools:sigma",
        "teams:admin",
        "admin",
    }
)


class TokenRecord(BaseSettings):
    name: str
    digest: str
    scopes: frozenset[str]

    model_config = SettingsConfigDict(frozen=True)


def read_secret(value: SecretStr | None, file_path: Path | None) -> str:
    if value and value.get_secret_value():
        return value.get_secret_value()
    if file_path:
        return file_path.read_text(encoding="utf-8").strip()
    return ""


def parse_token_records(raw: str) -> tuple[TokenRecord, ...]:
    records: list[TokenRecord] = []
    names: set[str] = set()
    for item in filter(None, (part.strip() for part in raw.split(";"))):
        try:
            name, digest, scopes_csv = item.split(":", 2)
        except ValueError as exc:
            raise ValueError("token records must use name:sha256:scope,scope") from exc
        scopes = frozenset(filter(None, (scope.strip() for scope in scopes_csv.split(","))))
        if not name or name in names:
            raise ValueError("token record names must be unique and non-empty")
        if not TOKEN_DIGEST.fullmatch(digest):
            raise ValueError(f"token record {name!r} does not contain a SHA-256 digest")
        if len(set(digest)) < 4:
            raise ValueError(f"token record {name!r} contains a placeholder digest")
        unknown = scopes - ALL_SCOPES
        if unknown:
            raise ValueError(f"token record {name!r} contains unknown scopes: {sorted(unknown)}")
        if not scopes:
            raise ValueError(f"token record {name!r} must contain at least one scope")
        records.append(TokenRecord(name=name, digest=digest, scopes=scopes))
        names.add(name)
    return tuple(records)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SPRINTER_",
        env_file=None,
        extra="ignore",
        case_sensitive=False,
    )

    environment: Literal["development", "production"] = "production"
    host: str = "127.0.0.1"
    port: int = Field(default=8080, ge=1, le=65535)
    database_path: Path = Path("/var/lib/sprinter/sprinter.db")
    log_level: str = "INFO"

    api_token_records: str = ""
    max_body_bytes: int = Field(default=1_048_576, ge=1, le=16_777_216)
    rate_limit_per_minute: int = Field(default=60, ge=1, le=100_000)
    worker_poll_seconds: float = Field(default=2.0, ge=0.1, le=60)
    worker_stale_seconds: int = Field(default=120, ge=10, le=3600)
    job_max_attempts: int = Field(default=5, ge=1, le=20)
    job_retention_days: int = Field(default=90, ge=1)
    evidence_retention_days: int = Field(default=180, ge=1)
    audit_retention_days: int = Field(default=365, ge=1)
    teams_installation_retention_days: int = Field(default=365, ge=1)

    pi_command: str = "pi"
    pi_expected_version: str = PI_VERSION
    pi_provider: str = ""
    pi_model: str = ""
    pi_thinking: Literal["off", "minimal", "low", "medium", "high", "xhigh", "max"] = "high"
    pi_timeout_seconds: int = Field(default=180, ge=10, le=900)
    pi_max_output_bytes: int = Field(default=262_144, ge=4096, le=4_194_304)
    pi_probe_interval_seconds: int = Field(default=900, ge=60, le=86_400)
    model_data_policy_ack: bool = False
    prompt_max_rows: int = Field(default=20, ge=1, le=100)
    prompt_extra_redact_keys: str = ""

    splunk_base_url: str = ""
    splunk_web_url: str = ""
    splunk_hec_url: str = ""
    splunk_hec_token: SecretStr | None = None
    splunk_hec_token_file: Path | None = None
    splunk_username: str = ""
    splunk_password: SecretStr | None = None
    splunk_password_file: Path | None = None
    splunk_ca_file: Path | None = None
    splunk_allowed_indexes: str = ""
    splunk_default_earliest: str = "-24h"

    adx_cluster_url: str = ""
    adx_database: str = ""
    adx_tenant_id: str = ""
    adx_client_id: str = ""
    adx_client_secret: SecretStr | None = None
    adx_client_secret_file: Path | None = None
    adx_allowed_tables: str = ""

    confluence_base_url: str = ""
    confluence_email: str = ""
    confluence_api_token: SecretStr | None = None
    confluence_api_token_file: Path | None = None
    confluence_allowed_spaces: str = ""

    teams_enabled: bool = False
    teams_app_id: str = ""
    teams_tenant_id: str = ""
    teams_client_secret: SecretStr | None = None
    teams_client_secret_file: Path | None = None
    teams_allowed_tenant_ids: str = ""
    teams_public_base_url: str = ""

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        value = value.upper()
        if value not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("invalid log level")
        return value

    @model_validator(mode="after")
    def reject_legacy_environment(self) -> Settings:
        legacy = sorted(key for key in os.environ if key.startswith("ANALYST_"))
        if legacy:
            raise ValueError(f"legacy ANALYST_* configuration is not supported: {', '.join(legacy)}")
        return self

    @property
    def token_records(self) -> tuple[TokenRecord, ...]:
        return parse_token_records(self.api_token_records)

    @property
    def allowed_splunk_indexes(self) -> frozenset[str]:
        return frozenset(part.strip() for part in self.splunk_allowed_indexes.split(",") if part.strip())

    @property
    def allowed_adx_tables(self) -> frozenset[str]:
        return frozenset(part.strip() for part in self.adx_allowed_tables.split(",") if part.strip())

    @property
    def allowed_confluence_spaces(self) -> frozenset[str]:
        return frozenset(part.strip() for part in self.confluence_allowed_spaces.split(",") if part.strip())

    @property
    def allowed_teams_tenants(self) -> frozenset[str]:
        return frozenset(part.strip() for part in self.teams_allowed_tenant_ids.split(",") if part.strip())

    @property
    def redaction_keys(self) -> frozenset[str]:
        defaults = {
            "authorization",
            "password",
            "secret",
            "token",
            "api_key",
            "apikey",
            "credential",
            "cookie",
        }
        defaults.update(
            part.strip().lower()
            for part in self.prompt_extra_redact_keys.split(",")
            if part.strip()
        )
        return frozenset(defaults)

    def secret_value(self, name: Literal["splunk", "adx", "confluence", "teams"]) -> str:
        if name == "splunk":
            return read_secret(self.splunk_password, self.splunk_password_file)
        if name == "adx":
            return read_secret(self.adx_client_secret, self.adx_client_secret_file)
        if name == "confluence":
            return read_secret(self.confluence_api_token, self.confluence_api_token_file)
        return read_secret(self.teams_client_secret, self.teams_client_secret_file)

    def validate_runtime(self, role: Literal["api", "worker", "ready"]) -> None:
        errors: list[str] = []
        if not self.token_records:
            errors.append("SPRINTER_API_TOKEN_RECORDS is required")
        if self.pi_expected_version != PI_VERSION:
            errors.append(f"SPRINTER_PI_EXPECTED_VERSION must remain pinned to {PI_VERSION}")
        if not self.pi_provider or not self.pi_model:
            errors.append("SPRINTER_PI_PROVIDER and SPRINTER_PI_MODEL are required")
        if not self.model_data_policy_ack:
            errors.append("SPRINTER_MODEL_DATA_POLICY_ACK=1 is required")
        for path_name, path in (
            ("SPRINTER_SPLUNK_CA_FILE", self.splunk_ca_file),
            ("SPRINTER_SPLUNK_PASSWORD_FILE", self.splunk_password_file),
            ("SPRINTER_SPLUNK_HEC_TOKEN_FILE", self.splunk_hec_token_file),
            ("SPRINTER_ADX_CLIENT_SECRET_FILE", self.adx_client_secret_file),
            ("SPRINTER_CONFLUENCE_API_TOKEN_FILE", self.confluence_api_token_file),
            ("SPRINTER_TEAMS_CLIENT_SECRET_FILE", self.teams_client_secret_file),
        ):
            if path and (not path.is_file() or path.stat().st_mode & 0o077):
                errors.append(f"{path_name} must be a private readable file")
        if self.splunk_base_url:
            if not self.splunk_base_url.startswith("https://"):
                errors.append("SPRINTER_SPLUNK_BASE_URL must use HTTPS")
            if not self.allowed_splunk_indexes:
                errors.append("SPRINTER_SPLUNK_ALLOWED_INDEXES is required when Splunk is configured")
            if not self.splunk_username or not self.secret_value("splunk"):
                errors.append("Splunk username and password secret are required")
        if self.splunk_hec_url:
            if not self.splunk_hec_url.startswith("https://"):
                errors.append("SPRINTER_SPLUNK_HEC_URL must use HTTPS")
            if not read_secret(self.splunk_hec_token, self.splunk_hec_token_file):
                errors.append("Splunk HEC token secret is required")
        if self.adx_cluster_url:
            if not self.adx_cluster_url.startswith("https://"):
                errors.append("SPRINTER_ADX_CLUSTER_URL must use HTTPS")
            if not all((self.adx_database, self.adx_tenant_id, self.adx_client_id, self.secret_value("adx"))):
                errors.append("ADX database and client credentials are required")
        if self.confluence_base_url:
            if not self.confluence_base_url.startswith("https://"):
                errors.append("SPRINTER_CONFLUENCE_BASE_URL must use HTTPS")
            if not self.confluence_email or not self.secret_value("confluence"):
                errors.append("Confluence email and API token secret are required")
        if self.teams_enabled:
            if not all((self.teams_app_id, self.teams_tenant_id, self.secret_value("teams"))):
                errors.append("Teams app, tenant, and client secret configuration are required")
            if not self.allowed_teams_tenants:
                errors.append("SPRINTER_TEAMS_ALLOWED_TENANT_IDS is required")
            if not self.teams_public_base_url.startswith("https://"):
                errors.append("SPRINTER_TEAMS_PUBLIC_BASE_URL must use HTTPS")
        if self.environment == "production" and self.host not in {"127.0.0.1", "::1"}:
            errors.append("SPRINTER_HOST must bind to loopback; container exposure is configured separately")
        if role == "worker" and not os.access(self.database_path.parent, os.W_OK):
            errors.append(f"database directory is not writable: {self.database_path.parent}")
        if errors:
            raise ValueError("; ".join(errors))

    @staticmethod
    def hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()


@lru_cache
def get_settings() -> Settings:
    return Settings()
