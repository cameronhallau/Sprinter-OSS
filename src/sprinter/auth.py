from __future__ import annotations

import hmac
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from threading import Lock
from typing import Any

from fastapi import HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from sprinter.config import Settings, TokenRecord

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    name: str
    scopes: frozenset[str]

    def permits(self, scope: str) -> bool:
        return "admin" in self.scopes or scope in self.scopes


class TokenAuthenticator:
    def __init__(self, settings: Settings):
        self.records: tuple[TokenRecord, ...] = settings.token_records

    def authenticate(self, token: str) -> Principal | None:
        digest = Settings.hash_token(token)
        matched: TokenRecord | None = None
        for record in self.records:
            if hmac.compare_digest(digest, record.digest):
                matched = record
        if not matched:
            return None
        return Principal(name=matched.name, scopes=matched.scopes)


class SlidingWindowRateLimiter:
    def __init__(self, requests_per_minute: int):
        self.limit = requests_per_minute
        self.events: dict[str, deque[float]] = defaultdict(deque)
        self.lock = Lock()

    def check(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - 60
        with self.lock:
            events = self.events[key]
            while events and events[0] < cutoff:
                events.popleft()
            if len(events) >= self.limit:
                return False
            events.append(now)
            return True


def require_scope(scope: str) -> Callable[[Request], Awaitable[Principal]]:
    async def dependency(request: Request) -> Principal:
        credentials: HTTPAuthorizationCredentials | None = await bearer(request)
        if not credentials or credentials.scheme.lower() != "bearer":
            request.app.state.container.audit("auth.failed", "anonymous", {"reason": "missing_token"})
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="missing bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        container: Any = request.app.state.container
        principal: Principal | None = container.authenticator.authenticate(credentials.credentials)
        if not principal:
            request.app.state.container.audit("auth.failed", "anonymous", {"reason": "invalid_token"})
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        client = request.client.host if request.client else "unknown"
        if not request.app.state.container.rate_limiter.check(f"{principal.name}:{client}"):
            request.app.state.container.audit("rate_limited", principal.name, {"client": client})
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="rate limit exceeded")
        if not principal.permits(scope):
            request.app.state.container.audit(
                "auth.forbidden",
                principal.name,
                {"required_scope": scope},
            )
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient scope")
        return principal

    return dependency
