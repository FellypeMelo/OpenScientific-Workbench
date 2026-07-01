import pytest
from fastapi.testclient import TestClient
from uuid import uuid4
from src.presentation.main import app

client = TestClient(app)

def test_create_session_endpoint():
    user_id = str(uuid4())
    workspace_id = str(uuid4())
    
    # This will fail initially (RED) because app/routes are not fully mounted
    # or the dependencies are not mocked.
    response = client.post(
        "/api/v1/sessions",
        json={"user_id": user_id, "workspace_id": workspace_id}
    )
    assert response.status_code == 201
    data = response.json()
    assert "id" in data
    assert data["session_status"] == "INITIALIZING"

def test_chat_streaming_endpoint():
    session_id = str(uuid4())
    response = client.post(
        f"/api/v1/sessions/{session_id}/chat",
        json={"prompt": "Test query"}
    )
    assert response.status_code == 200
    # Assert it returns a streaming connection (SSE)
    assert "text/event-stream" in response.headers["content-type"]
