"""
Unit tests for the `CORSMiddleware` registration in `presentation/main.py`
(Fase 5 - frontend gap closure).

Without this, the Next.js frontend (a different origin from this API -- see
`frontend/src/lib/api-client.ts`'s `NEXT_PUBLIC_API_URL`) could not call any
route at all: a real browser rejects cross-origin responses missing CORS
headers, and for any request carrying a custom header (this API requires
`Authorization: Bearer <token>` on nearly every route, see
`middleware/jwt_auth.py`) the browser first sends a CORS *preflight* `OPTIONS`
request with no bearer token -- which `JWTAuthMiddleware` would otherwise 401,
since `CORSMiddleware` must run outermost (added last) to intercept and answer
preflight requests before the auth layer ever sees them.
"""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.infrastructure.config import settings
from src.presentation.main import app
from src.presentation.middleware.jwt_auth import create_access_token

FRONTEND_ORIGIN = "http://localhost:3000"


def test_default_allowed_origin_matches_the_frontend_dev_server():
    assert FRONTEND_ORIGIN in settings.cors_allowed_origins


def test_preflight_request_on_a_protected_route_is_answered_without_a_token():
    """
    A CORS preflight is an `OPTIONS` request with `Origin` +
    `Access-Control-Request-Method` headers and (deliberately, per the CORS
    spec) no `Authorization` header. If `JWTAuthMiddleware` ran before
    `CORSMiddleware`, this would 401; since `CORSMiddleware` is registered as
    the outermost layer, it must short-circuit and answer this itself.
    """
    with TestClient(app) as client:
        response = client.options(
            f"/api/v1/sessions/{uuid4()}",
            headers={
                "Origin": FRONTEND_ORIGIN,
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == FRONTEND_ORIGIN


def test_actual_request_from_allowed_origin_gets_cors_headers():
    token = create_access_token(uuid4(), iam_role="scientist")
    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/sessions/{uuid4()}",
            headers={"Authorization": f"Bearer {token}", "Origin": FRONTEND_ORIGIN},
        )

    # 404 (session not found) is expected here -- the point is the CORS header
    # is present on the response regardless of the route's own status code.
    assert response.status_code == 404
    assert response.headers["access-control-allow-origin"] == FRONTEND_ORIGIN


class TestCorsAllowedOriginsParsing:
    def test_splits_comma_separated_origins_and_strips_whitespace(self, monkeypatch):
        monkeypatch.setattr(
            settings, "CORS_ALLOWED_ORIGINS", "http://localhost:3000, https://osw.example.org ,"
        )
        assert settings.cors_allowed_origins == [
            "http://localhost:3000",
            "https://osw.example.org",
        ]

    def test_empty_string_yields_no_allowed_origins(self, monkeypatch):
        monkeypatch.setattr(settings, "CORS_ALLOWED_ORIGINS", "")
        assert settings.cors_allowed_origins == []
