from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any, cast

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from sprinter import __version__
from sprinter.auth import Principal, require_scope
from sprinter.config import Settings, get_settings
from sprinter.db import IdempotencyConflict
from sprinter.engine import Container
from sprinter.schemas import (
    AdxQueryRequest,
    ConfluenceSearchRequest,
    HealthView,
    InstallationUpdate,
    InstallationView,
    JobView,
    ReadyView,
    ReviewJobAccepted,
    ReviewJobRequest,
    SigmaConvertRequest,
    SplunkSearchRequest,
)
from sprinter.teams.gateway import TeamsAuthenticationError


class BodyLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        content_length = dict(scope.get("headers") or []).get(b"content-length")
        if content_length:
            try:
                too_large = int(content_length) > self.max_bytes
            except ValueError:
                response = JSONResponse({"detail": "invalid content length"}, status_code=400)
                await response(scope, receive, send)
                return
            if too_large:
                response = JSONResponse({"detail": "request body too large"}, status_code=413)
                await response(scope, receive, send)
                return
        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise HTTPException(status_code=413, detail="request body too large")
            return message

        try:
            await self.app(scope, limited_receive, send)
        except HTTPException as exc:
            await JSONResponse({"detail": exc.detail}, status_code=exc.status_code)(scope, receive, send)


def installation_view(item: Any) -> InstallationView:
    return InstallationView(
        id=item.id,
        tenant_id=item.tenant_id,
        conversation_id=item.conversation_id,
        service_url=item.service_url,
        scope=item.scope,
        enabled=item.enabled,
        active=item.active,
        discovered_at=item.discovered_at.isoformat(),
        last_seen_at=item.last_seen_at.isoformat(),
    )


def request_container(request: Request) -> Container:
    return cast(Container, request.app.state.container)


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings.validate_runtime("api")
        app.state.container = container or Container(settings)
        yield

    app = FastAPI(
        title="Sprinter API",
        version=__version__,
        docs_url="/api/docs" if settings.environment == "development" else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.environment == "development" else None,
        lifespan=lifespan,
    )
    app.add_middleware(BodyLimitMiddleware, max_bytes=settings.max_body_bytes)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=400, content=jsonable_encoder({"detail": exc.errors()}))

    @app.exception_handler(IdempotencyConflict)
    async def idempotency_conflict(_request: Request, exc: IdempotencyConflict) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(ValueError)
    async def bad_request(_request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(RuntimeError)
    async def dependency_unavailable(_request: Request, _exc: RuntimeError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": "configured dependency is unavailable"})

    @app.get("/livez", response_model=HealthView)
    async def livez() -> HealthView:
        return HealthView(ok=True, version=__version__)

    @app.get("/readyz", response_model=ReadyView)
    async def readyz(
        request: Request,
        response: Response,
        _principal: Annotated[Principal, Depends(require_scope("admin"))],
    ) -> ReadyView:
        checks = request_container(request).db.readiness()
        teams_ready = (
            not settings.teams_enabled
            or checks["enabled_teams_destinations"] > 0
        )
        checks["teams_ready"] = teams_ready
        checks["pi_version_expected"] = settings.pi_expected_version
        ok = bool(checks["database"] and checks["worker_fresh"] and checks["pi_ready"] and teams_ready)
        if not ok:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadyView(ok=ok, checks=checks)

    @app.post("/api/v1/review-jobs", status_code=202, response_model=ReviewJobAccepted)
    async def create_review_job(
        payload: ReviewJobRequest,
        request: Request,
        principal: Annotated[Principal, Depends(require_scope("reviews:write"))],
        idempotency_key: Annotated[str, Header(min_length=8, max_length=128, alias="Idempotency-Key")],
    ) -> ReviewJobAccepted:
        job, created = request_container(request).submit_review(payload, idempotency_key, principal.name)
        return ReviewJobAccepted(
            job_id=job.id,
            status=job.status,
            created=created,
            url=f"/api/v1/jobs/{job.id}",
        )

    @app.get("/api/v1/jobs/{job_id}", response_model=JobView)
    async def get_job(
        job_id: str,
        request: Request,
        _principal: Annotated[Principal, Depends(require_scope("jobs:read"))],
    ) -> dict[str, Any]:
        container = request_container(request)
        job = container.db.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        return container.job_view(job)

    @app.post("/api/v1/tools/splunk/search")
    async def splunk_search(
        payload: SplunkSearchRequest,
        request: Request,
        principal: Annotated[Principal, Depends(require_scope("tools:splunk"))],
    ) -> dict[str, Any]:
        container = request_container(request)
        result = container.splunk.search(
            payload.search,
            earliest=payload.earliest,
            latest=payload.latest,
            max_rows=payload.max_rows,
        )
        container.audit("tool.splunk", principal.name, {"search": result["search"]})
        return result

    @app.post("/api/v1/tools/adx/query")
    async def adx_query(
        payload: AdxQueryRequest,
        request: Request,
        principal: Annotated[Principal, Depends(require_scope("tools:adx"))],
    ) -> dict[str, Any]:
        container = request_container(request)
        result = container.adx.query(payload.query, payload.max_rows)
        container.audit("tool.adx", principal.name, {"query": result["query"]})
        return result

    @app.post("/api/v1/tools/confluence/search")
    async def confluence_search(
        payload: ConfluenceSearchRequest,
        request: Request,
        principal: Annotated[Principal, Depends(require_scope("tools:confluence"))],
    ) -> dict[str, Any]:
        container = request_container(request)
        result = container.confluence.search(payload.query, payload.limit)
        container.audit("tool.confluence", principal.name, {"query": payload.query})
        return result

    @app.post("/api/v1/tools/sigma/convert")
    async def sigma_convert(
        payload: SigmaConvertRequest,
        request: Request,
        principal: Annotated[Principal, Depends(require_scope("tools:sigma"))],
    ) -> dict[str, Any]:
        container = request_container(request)
        result = container.sigma.convert(payload.rule)
        container.audit("tool.sigma", principal.name, {"query_count": result["count"]})
        return result

    @app.post("/api/v1/teams/events", status_code=202)
    async def teams_events(request: Request, authorization: Annotated[str, Header()] = "") -> dict[str, Any]:
        container = request_container(request)
        if not settings.teams_enabled or not container.teams:
            raise HTTPException(status_code=404, detail="Teams is disabled")
        try:
            payload = await request.json()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="malformed JSON") from exc
        try:
            _claims, activity = await asyncio.to_thread(
                container.teams.validate_activity,
                authorization,
                payload,
            )
            return container.teams.handle_lifecycle(activity)
        except TeamsAuthenticationError as exc:
            container.audit("teams.auth_failed", "teams", {"reason": str(exc)})
            raise HTTPException(status_code=401, detail="invalid Teams activity") from exc

    @app.get("/api/v1/teams/installations", response_model=list[InstallationView])
    async def list_installations(
        request: Request,
        _principal: Annotated[Principal, Depends(require_scope("teams:admin"))],
    ) -> list[InstallationView]:
        return [installation_view(item) for item in request_container(request).db.installations()]

    @app.patch("/api/v1/teams/installations/{installation_id}", response_model=InstallationView)
    async def update_installation(
        installation_id: str,
        payload: InstallationUpdate,
        request: Request,
        principal: Annotated[Principal, Depends(require_scope("teams:admin"))],
    ) -> InstallationView:
        container = request_container(request)
        item = container.db.set_installation_enabled(installation_id, payload.enabled)
        if not item:
            raise HTTPException(status_code=409, detail="installation not found or inactive")
        container.audit(
            "teams.installation_updated",
            principal.name,
            {"installation_id": installation_id, "enabled": payload.enabled},
        )
        return installation_view(item)

    return app


def app_factory() -> FastAPI:
    return create_app()
