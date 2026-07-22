"""
Unit tests for `RateLimitMiddleware` (Fase 2 - security middleware; fail-closed
fallback for expensive routes added in the production-hardening phase).

Uses a hand-written fake `redis.asyncio.Redis` stand-in (injected via the
`redis_client` constructor parameter added specifically for testability) rather
than a real Redis connection or `fakeredis` dependency, since the middleware only
calls three commands (`incr`, `expire`, `ttl`) and a real client isn't needed to
exercise the fixed-window counting logic or the fail-open path.
"""
import logging

import pytest
import redis.exceptions
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.presentation.middleware.rate_limit import RateLimitMiddleware, _is_expensive_path


class _FakeRedis:
    """In-memory stand-in for the subset of the async redis client this middleware
    uses. Mirrors real Redis semantics closely enough for fixed-window testing:
    `INCR` on a fresh key returns 1, `EXPIRE` records a TTL, `TTL` reports it back."""

    def __init__(self):
        self.counts: dict[str, int] = {}
        self.expiries: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key: str, seconds: int) -> None:
        self.expiries[key] = seconds

    async def ttl(self, key: str) -> int:
        return self.expiries.get(key, -1)


class _UnreachableRedis:
    """Simulates a Redis backend that cannot be reached at all (e.g. no
    docker-compose running locally): every command raises a connection error."""

    async def incr(self, key: str) -> int:
        raise redis.exceptions.ConnectionError("Connection refused")

    async def expire(self, key: str, seconds: int) -> None:  # pragma: no cover - unreachable
        raise redis.exceptions.ConnectionError("Connection refused")

    async def ttl(self, key: str) -> int:  # pragma: no cover - unreachable
        raise redis.exceptions.ConnectionError("Connection refused")


def _build_test_app(redis_client, limit: int = 2, window_seconds: int = 60) -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        RateLimitMiddleware,
        redis_client=redis_client,
        limit=limit,
        window_seconds=window_seconds,
    )

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    return app


def test_requests_within_limit_pass_through():
    client = TestClient(_build_test_app(_FakeRedis(), limit=2))

    assert client.get("/ping").status_code == 200
    assert client.get("/ping").status_code == 200


def test_exceeding_limit_returns_429_with_retry_after_header():
    client = TestClient(_build_test_app(_FakeRedis(), limit=2, window_seconds=30))

    assert client.get("/ping").status_code == 200
    assert client.get("/ping").status_code == 200
    third = client.get("/ping")

    assert third.status_code == 429
    assert third.json()["error_code"] == 4290
    assert "Retry-After" in third.headers
    assert int(third.headers["Retry-After"]) > 0


def test_limit_is_scoped_per_client_key():
    """Two different `_client_key` values (simulated via two separate fake Redis
    instances, since the real key includes the caller's IP/user id) each get their
    own independent budget."""
    fake_a = _FakeRedis()
    fake_b = _FakeRedis()
    client_a = TestClient(_build_test_app(fake_a, limit=1))
    client_b = TestClient(_build_test_app(fake_b, limit=1))

    assert client_a.get("/ping").status_code == 200
    assert client_a.get("/ping").status_code == 429
    # A different backing store (i.e. a different bucket) is unaffected.
    assert client_b.get("/ping").status_code == 200


def test_redis_unreachable_fails_open(caplog):
    client = TestClient(_build_test_app(_UnreachableRedis(), limit=1))

    with caplog.at_level(logging.WARNING):
        response = client.get("/ping")

    assert response.status_code == 200
    assert "unreachable" in caplog.text.lower()


def test_rate_limit_config_defaults_are_positive_integers():
    from src.infrastructure.config import settings

    assert isinstance(settings.RATE_LIMIT_REQUESTS, int) and settings.RATE_LIMIT_REQUESTS > 0
    assert isinstance(settings.RATE_LIMIT_WINDOW_SECONDS, int) and settings.RATE_LIMIT_WINDOW_SECONDS > 0


class TestIsExpensivePath:
    def test_matches_the_chat_route_regardless_of_session_id(self):
        assert _is_expensive_path(
            "/api/v1/sessions/11111111-1111-1111-1111-111111111111/chat"
        )

    def test_matches_the_manuscript_compile_route(self):
        assert _is_expensive_path("/api/v1/manuscript/compile")

    def test_does_not_match_unrelated_or_neighboring_routes(self):
        assert not _is_expensive_path("/api/v1/sessions")
        assert not _is_expensive_path("/api/v1/sessions/11111111-1111-1111-1111-111111111111")
        assert not _is_expensive_path("/api/v1/manuscript")
        assert not _is_expensive_path("/api/v1/workspaces/abc/fork")
        assert not _is_expensive_path("/ping")


def _build_test_app_with_expensive_routes(redis_client, limit: int = 2, window_seconds: int = 60) -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        RateLimitMiddleware,
        redis_client=redis_client,
        limit=limit,
        window_seconds=window_seconds,
    )

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    @app.post("/api/v1/sessions/{session_id}/chat")
    async def chat(session_id: str):
        return {"ok": True}

    @app.post("/api/v1/manuscript/compile")
    async def compile_manuscript():
        return {"ok": True}

    return app


def test_redis_outage_still_throttles_the_chat_route_fail_closed(caplog):
    """
    Redis-outage-simulation test (production hardening): unlike the generic
    fail-open path, a Redis outage on the expensive chat route must still
    enforce SOME budget via the in-process fallback limiter, not let every
    request through uninspected.
    """
    client = TestClient(_build_test_app_with_expensive_routes(_UnreachableRedis(), limit=1))

    with caplog.at_level(logging.WARNING):
        first = client.post("/api/v1/sessions/abc-123/chat")
        second = client.post("/api/v1/sessions/abc-123/chat")

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["error_code"] == 4290
    assert "fail-closed" in caplog.text.lower()


def test_redis_outage_still_throttles_the_manuscript_compile_route_fail_closed():
    client = TestClient(_build_test_app_with_expensive_routes(_UnreachableRedis(), limit=1))

    assert client.post("/api/v1/manuscript/compile").status_code == 200
    second = client.post("/api/v1/manuscript/compile")
    assert second.status_code == 429
    assert "Retry-After" in second.headers


def test_redis_outage_still_fails_open_for_cheap_routes_on_the_same_middleware_instance():
    """
    The SAME middleware instance (and therefore the same Redis outage) must
    keep failing open for a route that isn't in the expensive allowlist --
    proving the fail-closed fallback is scoped to specific paths, not global.
    """
    client = TestClient(_build_test_app_with_expensive_routes(_UnreachableRedis(), limit=1))

    assert client.get("/ping").status_code == 200
    assert client.get("/ping").status_code == 200
    assert client.get("/ping").status_code == 200


class TestInProcessFixedWindowLimiter:
    """
    Direct unit coverage of `_InProcessFixedWindowLimiter` (the fail-closed
    fallback's own counting logic), independent of the ASGI/middleware plumbing
    exercised above.
    """

    def test_allows_requests_up_to_the_limit_then_rejects(self):
        from src.presentation.middleware.rate_limit import _InProcessFixedWindowLimiter

        limiter = _InProcessFixedWindowLimiter(limit=2, window_seconds=60)

        import asyncio

        async def run():
            first = await limiter.allow("k")
            second = await limiter.allow("k")
            third = await limiter.allow("k")
            return first, second, third

        first, second, third = asyncio.run(run())
        assert first == (True, 0)
        assert second == (True, 0)
        allowed, retry_after = third
        assert allowed is False
        assert retry_after > 0

    def test_window_resets_after_it_elapses(self, monkeypatch):
        from src.presentation.middleware import rate_limit as rate_limit_module

        limiter = rate_limit_module._InProcessFixedWindowLimiter(limit=1, window_seconds=10)

        fake_now = [1000.0]
        monkeypatch.setattr(rate_limit_module.time, "monotonic", lambda: fake_now[0])

        import asyncio

        async def run():
            first = await limiter.allow("k")
            # Still inside the same 10s window: budget of 1 is exhausted.
            second = await limiter.allow("k")
            # Advance well past the window boundary: a fresh window starts.
            fake_now[0] += 11
            third = await limiter.allow("k")
            return first, second, third

        first, second, third = asyncio.run(run())
        assert first[0] is True
        assert second[0] is False
        assert third[0] is True

    def test_keys_are_independent(self):
        from src.presentation.middleware.rate_limit import _InProcessFixedWindowLimiter

        limiter = _InProcessFixedWindowLimiter(limit=1, window_seconds=60)

        import asyncio

        async def run():
            a1 = await limiter.allow("client-a")
            b1 = await limiter.allow("client-b")
            a2 = await limiter.allow("client-a")
            return a1, b1, a2

        a1, b1, a2 = asyncio.run(run())
        assert a1[0] is True
        assert b1[0] is True
        assert a2[0] is False
