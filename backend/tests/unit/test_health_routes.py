"""
Unit tests for `GET /health` (liveness) and `GET /ready` (readiness) --
`src/presentation/routes/health.py`, production-hardening phase.

The DB/Redis dependency boundaries are mocked via `app.dependency_overrides`
(the same pattern `tests/conftest.py`'s `_isolated_test_database` fixture and
`tests/unit/test_middleware_rate_limit.py` already use), never by faking the
route's own business logic.
"""
from typing import AsyncGenerator

import pytest
from fastapi.testclient import TestClient

from src.infrastructure.persistence.database import get_db_session
from src.presentation.main import app
from src.presentation.routes.health import get_redis_client

client = TestClient(app)


class _FakeRedisOk:
    async def ping(self):
        return True

    async def aclose(self):
        return None


class _FakeRedisDown:
    async def ping(self):
        raise ConnectionError("redis is down")

    async def aclose(self):
        return None


class _FakeDbSessionOk:
    async def execute(self, *args, **kwargs):
        return None


class _FakeDbSessionDown:
    async def execute(self, *args, **kwargs):
        raise RuntimeError("db is down")


def _override_redis(fake) -> None:
    app.dependency_overrides[get_redis_client] = lambda: fake


def _override_db(fake_session) -> None:
    async def _fake_get_db_session() -> AsyncGenerator:
        yield fake_session

    app.dependency_overrides[get_db_session] = _fake_get_db_session


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.pop(get_redis_client, None)
    app.dependency_overrides.pop(get_db_session, None)


def test_health_returns_200_without_auth_and_without_touching_dependencies():
    # No Authorization header at all -- must not 401 (allowlisted) -- and no
    # DB/Redis override is installed here, proving liveness makes no such
    # calls (an unconfigured Redis/Postgres would otherwise 500/hang it).
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_returns_200_when_db_and_redis_are_healthy():
    _override_redis(_FakeRedisOk())
    _override_db(_FakeDbSessionOk())

    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_ready_returns_503_naming_redis_when_redis_is_down():
    _override_redis(_FakeRedisDown())
    _override_db(_FakeDbSessionOk())

    response = client.get("/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert "redis" in body["failed_dependencies"]
    assert "database" not in body["failed_dependencies"]


def test_ready_returns_503_naming_database_when_database_is_down():
    _override_redis(_FakeRedisOk())
    _override_db(_FakeDbSessionDown())

    response = client.get("/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert "database" in body["failed_dependencies"]
    assert "redis" not in body["failed_dependencies"]


def test_ready_returns_503_naming_both_when_both_are_down():
    _override_redis(_FakeRedisDown())
    _override_db(_FakeDbSessionDown())

    response = client.get("/ready")
    assert response.status_code == 503
    body = response.json()
    assert set(body["failed_dependencies"]) == {"database", "redis"}


def test_ready_and_health_are_reachable_without_a_bearer_token():
    # Regression guard for the `UNAUTHENTICATED_PATHS` allowlist entries in
    # `presentation/middleware/jwt_auth.py`.
    _override_redis(_FakeRedisOk())
    _override_db(_FakeDbSessionOk())

    assert client.get("/health").status_code != 401
    assert client.get("/ready").status_code != 401
