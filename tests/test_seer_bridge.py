from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from urllib.request import Request

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "submit_seer_run.py"
SPEC = importlib.util.spec_from_file_location("submit_seer_run", SCRIPT)
assert SPEC and SPEC.loader
bridge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bridge)


class FakeResponse:
    status = 202

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return b'{"job_id":"job-1","status":"pending","created":true,"url":"/api/v1/jobs/job-1"}'


class FakeOpener:
    def __init__(self) -> None:
        self.request: Request | None = None
        self.timeout: int | None = None

    def open(self, request: Request, timeout: int) -> FakeResponse:
        self.request = request
        self.timeout = timeout
        return FakeResponse()


def test_bridge_builds_stable_seer_review_contract() -> None:
    payload, run_id = bridge.build_payload(
        {"run_id": "run-123", "workflow": "stix_ingest", "ioc_matches": 2}
    )
    assert run_id == "run-123"
    assert payload["selector"] == {"type": "run", "run_id": "run-123", "workflow": "stix_ingest"}
    assert payload["source"] == "seer-stix-runner"

    opener = FakeOpener()
    response = bridge.submit(
        base_url="https://sprinter.example",
        token="secret",  # noqa: S106 - inert unit-test credential
        payload=payload,
        idempotency_key="seer:osint-bot:run-123",
        opener=opener,
    )
    assert response["job_id"] == "job-1"
    assert opener.timeout == 30
    assert opener.request is not None
    assert opener.request.full_url == "https://sprinter.example/api/v1/review-jobs"
    assert opener.request.get_header("Authorization") == "Bearer secret"
    assert opener.request.get_header("Idempotency-key") == "seer:osint-bot:run-123"
    assert json.loads(opener.request.data or b"{}") == payload


def test_bridge_requires_https_except_loopback() -> None:
    assert bridge.endpoint("http://127.0.0.1:8080").startswith("http://127.0.0.1")
    with pytest.raises(ValueError, match="must use HTTPS"):
        bridge.endpoint("http://sprinter.example")


def test_bridge_bounds_input_and_protects_token_file(tmp_path: Path) -> None:
    token = tmp_path / "token"
    token.write_text("a-secure-test-token-with-entropy")
    token.chmod(0o644)
    with pytest.raises(ValueError, match="group or other"):
        bridge.private_text_file(token, "token file")

    summary = tmp_path / "summary.json"
    summary.write_text('{"run_id":"run-1"}')
    assert bridge.load_summary(summary)["run_id"] == "run-1"

    summary.write_bytes(b"x" * (1_048_576 + 1))
    with pytest.raises(ValueError, match="exceeds"):
        bridge.load_summary(summary)
