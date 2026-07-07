import pytest
from fastapi.testclient import TestClient
from uuid import uuid4
from src.presentation.main import app
from src.presentation.middleware.jwt_auth import create_access_token

client = TestClient(app)

# All application routes now require a valid `Authorization: Bearer <token>` header
# (Fase 2 - JWT auth middleware applies globally). Mint one via the helper the
# middleware itself exposes for exactly this purpose (there is no login endpoint
# yet -- see `presentation/middleware/jwt_auth.py` module docstring).
_AUTH_HEADERS = {"Authorization": f"Bearer {create_access_token(uuid4(), iam_role='scientist')}"}

def test_create_session_endpoint():
    user_id = str(uuid4())
    workspace_id = str(uuid4())

    # This will fail initially (RED) because app/routes are not fully mounted
    # or the dependencies are not mocked.
    response = client.post(
        "/api/v1/sessions",
        json={"user_id": user_id, "workspace_id": workspace_id},
        headers=_AUTH_HEADERS,
    )
    assert response.status_code == 201
    data = response.json()
    assert "id" in data
    assert data["session_status"] == "INITIALIZING"

def test_chat_streaming_endpoint():
    session_id = str(uuid4())
    response = client.post(
        f"/api/v1/sessions/{session_id}/chat",
        json={"prompt": "Test query"},
        headers=_AUTH_HEADERS,
    )
    assert response.status_code == 200
    # Assert it returns a streaming connection (SSE)
    assert "text/event-stream" in response.headers["content-type"]
