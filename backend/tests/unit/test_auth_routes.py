"""
Unit tests for the dev-mode token issuance endpoint (`POST /api/v1/auth/token`,
`presentation/routes/auth.py`), added in Fase 5 to break the chicken-and-egg
problem created by Fase 2's global `JWTAuthMiddleware`: a frontend client has
no way to obtain its first bearer token if every route -- including a login
endpoint -- requires one already.
"""
from uuid import uuid4

import jwt
import pytest
from fastapi.testclient import TestClient

from src.infrastructure.config import settings
from src.presentation.main import app
from src.presentation.middleware.jwt_auth import _SIGNING_SECRET

client = TestClient(app)


def test_issue_token_returns_bearer_access_token():
    user_id = str(uuid4())

    response = client.post("/api/v1/auth/token", json={"user_id": user_id})

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert isinstance(body["access_token"], str) and body["access_token"]


def test_issued_token_carries_requested_claims_and_defaults_role_to_scientist():
    user_id = str(uuid4())

    response = client.post("/api/v1/auth/token", json={"user_id": user_id})
    token = response.json()["access_token"]

    claims = jwt.decode(token, _SIGNING_SECRET, algorithms=[settings.JWT_ALGORITHM])
    assert claims["sub"] == user_id
    assert claims["iam_role"] == "scientist"


def test_issue_token_honors_explicit_iam_role():
    user_id = str(uuid4())

    response = client.post(
        "/api/v1/auth/token", json={"user_id": user_id, "iam_role": "admin"}
    )
    token = response.json()["access_token"]

    claims = jwt.decode(token, _SIGNING_SECRET, algorithms=[settings.JWT_ALGORITHM])
    assert claims["iam_role"] == "admin"


def test_issued_token_is_accepted_by_the_jwt_auth_middleware_on_a_real_route():
    """
    End-to-end proof that a token minted via this endpoint round-trips through
    `JWTAuthMiddleware` and unlocks an otherwise-protected route (as opposed to
    only decoding correctly in isolation).
    """
    user_id = uuid4()
    workspace_id = uuid4()

    token_response = client.post("/api/v1/auth/token", json={"user_id": str(user_id)})
    token = token_response.json()["access_token"]

    session_response = client.post(
        "/api/v1/sessions",
        json={"user_id": str(user_id), "workspace_id": str(workspace_id)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert session_response.status_code == 201


def test_issue_token_rejects_missing_user_id():
    response = client.post("/api/v1/auth/token", json={})
    assert response.status_code == 422


def test_auth_token_endpoint_is_reachable_without_a_bearer_token():
    # Regression guard for the `UNAUTHENTICATED_PATHS` allowlist entry in
    # `presentation/middleware/jwt_auth.py`.
    response = client.post("/api/v1/auth/token", json={"user_id": str(uuid4())})
    assert response.status_code != 401
