from __future__ import annotations

from fastapi.testclient import TestClient

from sprinter.api import create_app


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_public_liveness_and_no_legacy_routes(settings, container) -> None:
    with TestClient(create_app(settings, container)) as client:
        assert client.get("/livez").json()["ok"] is True
        for path in ("/health", "/teams/messages", "/jobs/review-run", "/approvals/x/approve"):
            assert client.get(path).status_code == 404


def test_authentication_and_scope_distinction(settings, container, api_token) -> None:
    with TestClient(create_app(settings, container)) as client:
        assert client.get("/readyz").status_code == 401
        assert client.get("/readyz", headers=auth("wrong-token")).status_code == 401
        response = client.get("/readyz", headers=auth(api_token))
        assert response.status_code == 503
        assert response.json()["ok"] is False


def test_submit_and_replay_job(settings, container, api_token) -> None:
    payload = {
        "selector": {"type": "run", "run_id": "run-123", "workflow": "stix_ingest"},
        "source": "stix-runner",
        "summary": {"evidence": [{"kind": "event", "payload": {"host": "lab-1"}}]},
    }
    headers = {**auth(api_token), "Idempotency-Key": "stix-run-123"}
    with TestClient(create_app(settings, container)) as client:
        created = client.post("/api/v1/review-jobs", json=payload, headers=headers)
        replay = client.post("/api/v1/review-jobs", json=payload, headers=headers)
        assert created.status_code == 202
        assert created.json()["created"] is True
        assert replay.json()["created"] is False
        assert replay.json()["job_id"] == created.json()["job_id"]
        job = client.get(created.json()["url"], headers=auth(api_token))
        assert job.status_code == 200
        assert job.json()["status"] == "pending"


def test_idempotency_key_conflict_returns_409(settings, container, api_token) -> None:
    headers = {**auth(api_token), "Idempotency-Key": "same-key-different-input"}
    with TestClient(create_app(settings, container)) as client:
        first = client.post(
            "/api/v1/review-jobs",
            json={"selector": {"type": "run", "run_id": "run-1"}},
            headers=headers,
        )
        conflict = client.post(
            "/api/v1/review-jobs",
            json={"selector": {"type": "run", "run_id": "run-2"}},
            headers=headers,
        )
        assert first.status_code == 202
        assert conflict.status_code == 409


def test_missing_idempotency_and_bad_json_are_400(settings, container, api_token) -> None:
    with TestClient(create_app(settings, container)) as client:
        missing = client.post(
            "/api/v1/review-jobs",
            json={"selector": {"type": "latest"}},
            headers=auth(api_token),
        )
        malformed = client.post(
            "/api/v1/review-jobs",
            content=b"{",
            headers={**auth(api_token), "Idempotency-Key": "malformed-json"},
        )
        assert missing.status_code == 400
        assert malformed.status_code == 400


def test_body_limit_returns_413(settings, container, api_token) -> None:
    limited = settings.model_copy(update={"max_body_bytes": 32})
    with TestClient(create_app(limited, container)) as client:
        response = client.post(
            "/api/v1/review-jobs",
            content=b"x" * 33,
            headers={
                **auth(api_token),
                "Idempotency-Key": "large-payload",
                "Content-Type": "application/json",
            },
        )
        assert response.status_code == 413


def test_rate_limit_returns_429(settings, container, api_token) -> None:
    limited = settings.model_copy(update={"rate_limit_per_minute": 1})
    container.rate_limiter.limit = 1
    with TestClient(create_app(limited, container)) as client:
        assert client.get("/readyz", headers=auth(api_token)).status_code == 503
        assert client.get("/readyz", headers=auth(api_token)).status_code == 429
