from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator


class RunSelector(BaseModel):
    type: Literal["run"]
    run_id: str = Field(min_length=1, max_length=256)
    workflow: str | None = Field(default=None, max_length=128)


class ResultSelector(BaseModel):
    type: Literal["result"]
    result_id: str = Field(min_length=1, max_length=256)


class LatestSelector(BaseModel):
    type: Literal["latest"]
    earliest: str = Field(default="-24h", pattern=r"^-[1-9][0-9]*[smhdw]$")


ReviewSelector = Annotated[RunSelector | ResultSelector | LatestSelector, Field(discriminator="type")]


class ReviewJobRequest(BaseModel):
    selector: ReviewSelector
    source: str = Field(default="api", min_length=1, max_length=128)
    summary: dict[str, Any] = Field(default_factory=dict)
    limit: int = Field(default=20, ge=1, le=100)


class ReviewJobAccepted(BaseModel):
    job_id: str
    status: str
    created: bool
    url: str


class EvidenceView(BaseModel):
    id: str
    kind: str
    title: str
    uri: str


class JobView(BaseModel):
    job_id: str
    status: str
    attempts: int
    max_attempts: int
    selector: dict[str, Any]
    source: str
    result: dict[str, Any] | None
    error: dict[str, Any] | None
    evidence: list[EvidenceView]
    created_at: str
    updated_at: str


class ModelDecision(BaseModel):
    verdict: Literal["true_positive", "false_positive", "needs_investigation", "no_finding"]
    severity: Literal["informational", "low", "medium", "high", "critical"]
    summary: str = Field(min_length=1, max_length=1000)
    rationale: list[str] = Field(min_length=1, max_length=10)
    recommended_actions: list[str] = Field(default_factory=list, max_length=10)
    evidence_ids: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("rationale", "recommended_actions")
    @classmethod
    def bound_text(cls, values: list[str]) -> list[str]:
        return [value.strip()[:1000] for value in values if value.strip()]


class SplunkSearchRequest(BaseModel):
    search: str = Field(min_length=1, max_length=8192)
    earliest: str = Field(default="-24h", max_length=32)
    latest: str = Field(default="now", max_length=32)
    max_rows: int = Field(default=50, ge=1, le=500)


class AdxQueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=16_384)
    max_rows: int = Field(default=50, ge=1, le=500)


class ConfluenceSearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=512)
    limit: int = Field(default=10, ge=1, le=50)


class SigmaConvertRequest(BaseModel):
    rule: dict[str, Any]


class InstallationUpdate(BaseModel):
    enabled: bool


class InstallationView(BaseModel):
    id: str
    tenant_id: str
    conversation_id: str
    service_url: str
    scope: str
    enabled: bool
    active: bool
    discovered_at: str
    last_seen_at: str


class HealthView(BaseModel):
    ok: bool
    service: Literal["sprinter"] = "sprinter"
    version: str


class ReadyView(BaseModel):
    ok: bool
    checks: dict[str, Any]


class EvidenceLink(BaseModel):
    label: str = Field(max_length=120)
    url: HttpUrl
