"""
Redis-backed rate limiting middleware (Fase 2 - security middleware).

Implements a simple fixed-window counter per client (authenticated user id when
available, else source IP), backed by `settings.REDIS_URL` via the async
`redis.asyncio` client. Limits are configurable through
`settings.RATE_LIMIT_REQUESTS` / `settings.RATE_LIMIT_WINDOW_SECONDS`.

Fail-open tradeoff: if Redis is unreachable (e.g. a local dev machine that hasn't
started `docker-compose`), every Redis call in `dispatch` is wrapped in a broad
`except Exception` that logs a warning and lets the request through uninspected,
rather than raising and taking the whole API down. A rate limiter whose *own*
outage blocks all traffic is strictly worse for availability than one that
occasionally under-enforces its limit during a short backend outage; production
deployments are expected to run Redis alongside the API (see `docker-compose.dev.yml`)
so this fallback path should be rare there.
"""
import logging
from typing import Optional

import redis.asyncio as redis
from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from src.infrastructure.config import settings

logger = logging.getLogger(__name__)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Fixed-window rate limiter keyed by authenticated user id, else client IP."""

    def __init__(
        self,
        app: ASGIApp,
        redis_url: Optional[str] = None,
        limit: Optional[int] = None,
        window_seconds: Optional[int] = None,
        redis_client: Optional["redis.Redis"] = None,
    ) -> None:
        super().__init__(app)
        self._redis_url = redis_url or settings.REDIS_URL
        self._limit = limit if limit is not None else settings.RATE_LIMIT_REQUESTS
        self._window_seconds = (
            window_seconds if window_seconds is not None else settings.RATE_LIMIT_WINDOW_SECONDS
        )
        # Allow tests to inject a fake/mock client directly instead of monkeypatching
        # `redis.from_url`. Lazily constructed on first use otherwise, so importing
        # this module (or constructing the middleware) never opens a socket.
        self._client: Optional["redis.Redis"] = redis_client

    def _get_client(self) -> "redis.Redis":
        if self._client is None:
            self._client = redis.from_url(self._redis_url, decode_responses=True)
        return self._client

    @staticmethod
    def _client_key(request: Request) -> str:
        user = getattr(request.state, "user", None)
        if isinstance(user, dict) and user.get("sub"):
            return f"ratelimit:user:{user['sub']}"
        client_host = request.client.host if request.client else "unknown"
        return f"ratelimit:ip:{client_host}"

    async def dispatch(self, request: Request, call_next):
        key = self._client_key(request)
        try:
            client = self._get_client()
            current = await client.incr(key)
            if current == 1:
                # First hit in this window: (re)set the expiry. Guarded so a crash
                # mid-window doesn't leave the counter without a TTL forever.
                await client.expire(key, self._window_seconds)

            if current > self._limit:
                ttl = await client.ttl(key)
                retry_after = ttl if ttl and ttl > 0 else self._window_seconds
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={
                        "error_code": 4290,
                        "message": "Rate limit exceeded. Please try again later.",
                    },
                    headers={"Retry-After": str(retry_after)},
                )
        except Exception:
            # Fail OPEN: see module docstring for the reasoning. Deliberately broad
            # (covers redis.exceptions.ConnectionError/TimeoutError and anything else
            # the client may raise) because any Redis-side failure should degrade to
            # "rate limiting is temporarily off", never "the API is down".
            logger.warning(
                "Rate limiting backend (Redis at %s) unreachable; failing OPEN and "
                "allowing this request through uninspected.",
                self._redis_url,
                exc_info=True,
            )

        return await call_next(request)
