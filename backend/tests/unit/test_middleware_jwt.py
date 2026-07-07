"""
Unit tests for `JWTAuthMiddleware` and its `create_access_token` /
`_resolve_signing_secret` helpers (Fase 2 - security middleware).

Two layers of coverage:
1. A minimal standalone ASGI app (built here) that only mounts `JWTAuthMiddleware`,
   so assertions about `request.state.user` and allowlist bypass don't depend on any
   real route's response shape.
2. A couple of smoke tests against the real application (`src.presentation.main.app`)
   proving the middleware is actually wired in globally (not just importable) and
   that the FastAPI docs routes remain reachable without a token.
"""
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from src.infrastructure.config import settings
from src.presentation.middleware.jwt_auth import (
    JWTAuthMiddleware,
    _resolve_signing_secret,
    create_access_token,
)


def _build_test_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(JWTAuthMiddleware)

    @app.get("/protected")
    async def protected(request: Request):
        return {"user": request.state.user}

    @app.get("/docs")
    async def fake_docs():
        # Shadows the allowlisted path with a trivial handler, so this test app can
        # prove the bypass works without depending on FastAPI's real Swagger UI.
        return {"ok": True}

    return app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(_build_test_app())


def test_missing_authorization_header_returns_401(client):
    response = client.get("/protected")
    assert response.status_code == 401
    assert response.json()["error_code"] == 4010


def test_malformed_authorization_header_returns_401(client):
    response = client.get("/protected", headers={"Authorization": "NotBearer abc"})
    assert response.status_code == 401


def test_invalid_token_returns_401(client):
    response = client.get("/protected", headers={"Authorization": "Bearer not-a-real-token"})
    assert response.status_code == 401


def test_bearer_prefix_with_empty_token_returns_401(client):
    response = client.get("/protected", headers={"Authorization": "Bearer "})
    assert response.status_code == 401


def test_extra_claims_are_included_in_minted_token(client):
    token = create_access_token(uuid4(), extra_claims={"workspace_id": "abc-123"})
    response = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["user"]["workspace_id"] == "abc-123"


def test_expired_token_returns_401(client):
    token = create_access_token(uuid4(), "scientist", expires_minutes=-1)
    response = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_valid_token_passes_through_and_attaches_claims(client):
    user_id = uuid4()
    token = create_access_token(user_id, iam_role="admin")

    response = client.get("/protected", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    user = response.json()["user"]
    assert user["sub"] == str(user_id)
    assert user["iam_role"] == "admin"


def test_allowlisted_path_bypasses_auth(client):
    response = client.get("/docs")
    assert response.status_code == 200


def test_real_app_requires_auth_on_api_routes():
    from src.presentation.main import app as real_app

    with TestClient(real_app) as real_client:
        response = real_client.get(f"/api/v1/sessions/{uuid4()}")
    assert response.status_code == 401


def test_real_app_allows_docs_without_auth():
    from src.presentation.main import app as real_app

    with TestClient(real_app) as real_client:
        response = real_client.get("/docs")
    assert response.status_code == 200


class TestResolveSigningSecret:
    """
    Directly exercises the JWT-secret-missing tradeoff described in
    `jwt_auth._resolve_signing_secret`'s docstring: fail loudly in production,
    fall back to a per-process ephemeral secret (with a logged warning) everywhere
    else. Calls the pure helper function directly rather than reimporting the
    module, since `_SIGNING_SECRET` is resolved once at import time and must not be
    disturbed for the other tests in this file/process.
    """

    def test_uses_configured_secret_when_present(self, monkeypatch):
        monkeypatch.setattr(settings, "JWT_SECRET", "configured-secret")
        assert _resolve_signing_secret() == "configured-secret"

    def test_raises_in_production_when_secret_missing(self, monkeypatch):
        monkeypatch.setattr(settings, "JWT_SECRET", None)
        monkeypatch.setattr(settings, "ENV", "production")
        with pytest.raises(RuntimeError):
            _resolve_signing_secret()

    def test_falls_back_to_ephemeral_secret_outside_production(self, monkeypatch, caplog):
        monkeypatch.setattr(settings, "JWT_SECRET", None)
        monkeypatch.setattr(settings, "ENV", "development")

        with caplog.at_level("WARNING"):
            secret_a = _resolve_signing_secret()
            secret_b = _resolve_signing_secret()

        assert secret_a and secret_b
        # No secret is persisted anywhere, so each resolution call mints a fresh
        # random value -- the middleware/`create_access_token` only ever agree
        # because they share the single `_SIGNING_SECRET` resolved once at import.
        assert secret_a != secret_b
        assert "ephemeral" in caplog.text
