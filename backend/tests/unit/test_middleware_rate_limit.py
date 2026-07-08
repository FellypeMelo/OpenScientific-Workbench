"""
Unit tests for `RateLimitMiddleware` (Fase 2 - security middleware).

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

from src.presentation.middleware.rate_limit import RateLimitMiddleware


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
