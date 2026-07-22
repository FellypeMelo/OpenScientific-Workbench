"""
Redis-backed rate limiting middleware (Fase 2 - security middleware; fail-closed
fallback for expensive routes added in the production-hardening phase).

Implements a simple fixed-window counter per client (authenticated user id when
available, else source IP), backed by `settings.REDIS_URL` via the async
`redis.asyncio` client. Limits are configurable through
`settings.RATE_LIMIT_REQUESTS` / `settings.RATE_LIMIT_WINDOW_SECONDS`.

Fail-open tradeoff (cheap routes ONLY): if Redis is unreachable (e.g. a local dev
machine that hasn't started `docker-compose`), every Redis call in `dispatch` is
wrapped in a broad `except Exception`. For most routes this logs a warning and lets
the request through uninspected, rather than raising and taking the whole API down --
a rate limiter whose *own* outage blocks all traffic is strictly worse for
availability than one that occasionally under-enforces its limit during a short
backend outage.

Fail-closed exception -- expensive routes (`_EXPENSIVE_PATH_PATTERNS`): chat
(`POST /api/v1/sessions/{id}/chat`, which streams tokens from a real BYOK LLM
provider -- i.e. spends the caller's/operator's money per request) and manuscript
compilation (`POST /api/v1/manuscript/compile`, a CPU-bound Tectonic subprocess
invocation) are cheap for an attacker to hammer but expensive for this service to
serve. Losing rate limiting on exactly these routes during a Redis outage would let
a Redis blip turn into an unbounded cost/CPU-exhaustion incident. For these paths
ONLY, a Redis exception falls back to `_InProcessFixedWindowLimiter` -- a
conservative, single-process, `asyncio.Lock`-guarded in-memory fixed-window counter
-- instead of failing open. It does not replicate Redis's cross-worker-shared-count
semantics (each process enforces its own budget independently), which is an
acceptable degradation: some over-permissiveness across a multi-replica deployment
during an outage is far better than zero enforcement on the routes that most need it.
"""
import asyncio
import logging
import re
import time
from typing import Dict, Optional, Pattern, Tuple

import redis.asyncio as redis
from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from src.infrastructure.config import settings

logger = logging.getLogger(__name__)

# Matched against `request.url.path`. Deliberately a short, explicit allowlist
# (not e.g. "everything under /api/v1") -- only routes that are genuinely
# expensive (real LLM provider spend, CPU-bound subprocess compilation) opt out
# of the fail-open default; every other route keeps failing open during a Redis
# outage per the module docstring above.
_EXPENSIVE_PATH_PATTERNS: Tuple[Pattern[str], ...] = (
    re.compile(r"^/api/v1/sessions/[^/]+/chat$"),
    re.compile(r"^/api/v1/manuscript/compile$"),
)


def _is_expensive_path(path: str) -> bool:
    return any(pattern.match(path) for pattern in _EXPENSIVE_PATH_PATTERNS)


class _InProcessFixedWindowLimiter:
    """
    Conservative, single-process fixed-window counter used ONLY as a fallback
    when Redis is unreachable, and ONLY for `_EXPENSIVE_PATH_PATTERNS` routes.

    Deliberately simple (an in-memory dict guarded by one `asyncio.Lock`, no
    cross-process coordination): the goal during a Redis outage is "still
    throttle each process's own view of traffic to *something* bounded" for
    the handful of expensive routes, not to reproduce Redis's exact
    multi-worker-shared-counter semantics.
    """

    def __init__(self, limit: int, window_seconds: int) -> None:
        self._limit = limit
        self._window_seconds = window_seconds
        self._lock = asyncio.Lock()
        # key -> (count_in_current_window, window_start_monotonic_seconds)
        self._counters: Dict[str, Tuple[int, float]] = {}

    async def allow(self, key: str) -> Tuple[bool, int]:
        """Returns `(allowed, retry_after_seconds)`."""
        now = time.monotonic()
        async with self._lock:
            count, window_start = self._counters.get(key, (0, now))
            if now - window_start >= self._window_seconds:
                # Window elapsed: start a fresh one.
                count, window_start = 0, now
            count += 1
            self._counters[key] = (count, window_start)

            if count > self._limit:
                retry_after = max(1, int(self._window_seconds - (now - window_start)))
                return False, retry_after
            return True, 0


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
        # Same numeric budget as the Redis-backed limiter, enforced per-process
        # instead of cluster-wide -- see `_InProcessFixedWindowLimiter`'s
        # docstring and the module docstring's "Fail-closed exception" section.
        self._fallback_limiter = _InProcessFixedWindowLimiter(
            limit=self._limit, window_seconds=self._window_seconds
        )

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

    @staticmethod
    def _too_many_requests(retry_after: int) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={
                "error_code": 4290,
                "message": "Rate limit exceeded. Please try again later.",
            },
            headers={"Retry-After": str(retry_after)},
        )

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
                return self._too_many_requests(retry_after)
        except Exception:
            # Deliberately broad (covers redis.exceptions.ConnectionError/
            # TimeoutError and anything else the client may raise): any
            # Redis-side failure means the *normal* multi-worker-consistent
            # counter is unavailable, regardless of the specific cause.
            if _is_expensive_path(request.url.path):
                # Fail CLOSED (via the in-process fallback): see the module
                # docstring's "Fail-closed exception" section.
                logger.warning(
                    "Rate limiting backend (Redis at %s) unreachable for expensive "
                    "path %s; falling back to a conservative in-process limiter "
                    "(fail-closed) instead of failing open.",
                    self._redis_url,
                    request.url.path,
                    exc_info=True,
                )
                allowed, retry_after = await self._fallback_limiter.allow(key)
                if not allowed:
                    return self._too_many_requests(retry_after)
            else:
                # Fail OPEN: see module docstring for the reasoning. A rate
                # limiter whose *own* outage blocks all traffic is strictly
                # worse for availability than one that occasionally
                # under-enforces its limit during a short backend outage.
                logger.warning(
                    "Rate limiting backend (Redis at %s) unreachable; failing OPEN "
                    "and allowing this request through uninspected.",
                    self._redis_url,
                    exc_info=True,
                )

        return await call_next(request)
