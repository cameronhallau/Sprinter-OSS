from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from sprinter.pi_gateway import PiGateway, PiProtocolError


def valid_decision() -> str:
    return (
        '{"verdict":"needs_investigation","severity":"medium","summary":"Review required",'
        '"rationale":["Evidence is incomplete"],"recommended_actions":["Inspect endpoint"],'
        '"evidence_ids":["e1"]}'
    )


def test_pi_is_strictly_isolated(settings) -> None:
    gateway = PiGateway(settings)
    assert gateway.argv == [
        "pi",
        "--mode",
        "rpc",
        "--provider",
        "openrouter",
        "--model",
        "test/model",
        "--thinking",
        "high",
        "--no-session",
        "--no-tools",
        "--no-extensions",
        "--no-skills",
        "--no-prompt-templates",
        "--no-context-files",
    ]
    assert gateway.environment["PI_TELEMETRY"] == "0"
    assert gateway.environment["PI_SKIP_VERSION_CHECK"] == "1"


@pytest.mark.asyncio
async def test_valid_review_is_schema_checked(settings, monkeypatch) -> None:
    gateway = PiGateway(settings)
    monkeypatch.setattr(gateway, "version", AsyncMock(return_value="0.83.0"))
    monkeypatch.setattr(gateway, "_rpc_prompt", AsyncMock(return_value=valid_decision()))
    result = await gateway.review("review")
    assert result.decision.verdict == "needs_investigation"
    assert result.pi_version == "0.83.0"


@pytest.mark.asyncio
async def test_one_schema_correction_then_failure(settings, monkeypatch) -> None:
    gateway = PiGateway(settings)
    monkeypatch.setattr(gateway, "version", AsyncMock(return_value="0.83.0"))
    prompt = AsyncMock(side_effect=["not-json", "still-not-json"])
    monkeypatch.setattr(gateway, "_rpc_prompt", prompt)
    with pytest.raises(PiProtocolError, match="after correction"):
        await gateway.review("review")
    assert prompt.await_count == 2


@pytest.mark.asyncio
async def test_wrong_pi_version_fails_closed(settings, monkeypatch) -> None:
    gateway = PiGateway(settings)
    monkeypatch.setattr(gateway, "version", AsyncMock(return_value="0.82.0"))
    with pytest.raises(Exception, match=r"expected 0\.83\.0"):
        await gateway.review("review")
