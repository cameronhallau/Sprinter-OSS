from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from sprinter.config import Settings
from sprinter.engine import Container


@pytest.fixture
def api_token() -> str:
    return "correct-horse-battery-staple"


@pytest.fixture
def settings(tmp_path: Path, api_token: str) -> Settings:
    digest = hashlib.sha256(api_token.encode()).hexdigest()
    return Settings(
        environment="development",
        database_path=tmp_path / "sprinter.db",
        api_token_records=(
            f"operator:{digest}:reviews:write,jobs:read,tools:splunk,tools:adx,"
            "tools:confluence,tools:sigma,teams:admin,admin"
        ),
        pi_provider="openrouter",
        pi_model="test/model",
        model_data_policy_ack=True,
        teams_enabled=False,
    )


@pytest.fixture
def container(settings: Settings) -> Container:
    return Container(settings, initialize_teams=False)
