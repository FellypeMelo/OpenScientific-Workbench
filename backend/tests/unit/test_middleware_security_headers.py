"""
Unit tests for `SecurityHeadersMiddleware` (Fase 2 - security middleware).

Checks both a minimal standalone app (to test the headers in isolation) and the
real application, since `SecurityHeadersMiddleware` is registered as the outermost
layer specifically so it also covers error responses (401/429) produced by the
other two middlewares.
"""
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.presentation.middleware.security_headers import SecurityHeadersMiddleware

EXPECTED_HEADERS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "strict-origin-when-cross-origin",
}


def _build_test_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    return app


def test_security_headers_present_on_successful_response():
    client = TestClient(_build_test_app())

    response = client.get("/ping")

    assert response.status_code == 200
    for header, value in EXPECTED_HEADERS.items():
        assert response.headers[header] == value
    assert "max-age" in response.headers["strict-transport-security"]
    assert response.headers["content-security-policy"] == "default-src 'self'"


def test_security_headers_present_on_real_app_success_response():
    from src.presentation.main import app as real_app
    from src.presentation.middleware.jwt_auth import create_access_token

    token = create_access_token(uuid4(), iam_role="scientist")
    with TestClient(real_app) as client:
        response = client.get(
            f"/api/v1/sessions/{uuid4()}",
            headers={"Authorization": f"Bearer {token}"},
        )

    # 404 (session not found) is still a response the security headers middleware
    # must have wrapped, since it is the outermost layer.
    assert response.status_code == 404
    for header, value in EXPECTED_HEADERS.items():
        assert response.headers[header] == value


def test_security_headers_present_on_401_response():
    """Proves headers are stamped even on responses short-circuited by an inner
    middleware (here, JWT auth rejecting an unauthenticated request), because
    `SecurityHeadersMiddleware` is registered as the outermost layer."""
    from src.presentation.main import app as real_app

    with TestClient(real_app) as client:
        response = client.get(f"/api/v1/sessions/{uuid4()}")

    assert response.status_code == 401
    for header, value in EXPECTED_HEADERS.items():
        assert response.headers[header] == value
