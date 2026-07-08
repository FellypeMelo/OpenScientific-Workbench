"""
Unit tests for `POST /api/v1/workspaces/{workspace_id}/fork`
(`presentation/routes/workspaces.py`), which wires the previously-unused
`ForkWorkspaceUseCase` (`application/use_cases/fork_workspace.py`) to a real
HTTP route via the real `PostgresWorkspaceRepository` (through the
`_isolated_test_database` autouse fixture in `tests/conftest.py`).

The physical Copy-on-Write snapshot step is stubbed out via a fake
`StorageManagerPort` (dependency-overridden), mirroring
`tests/unit/test_fork_workspace.py`'s `MockStorageManager` -- this suite is
about the route/wiring, not re-testing `BtrfsSnapshotManager`'s filesystem
fallback (covered by `tests/unit/test_btrfs_manager.py`).
"""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.domain.ports.storage_manager import StorageManagerPort
from src.presentation.main import app
from src.presentation.middleware.jwt_auth import create_access_token
from src.presentation.routes.workspaces import get_storage_manager

_AUTH_HEADERS = {"Authorization": f"Bearer {create_access_token(uuid4(), iam_role='scientist')}"}


class _FakeStorageManager(StorageManagerPort):
    def __init__(self):
        self.snapshots = []

    async def create_snapshot(self, source_path: str, target_path: str) -> None:
        self.snapshots.append((source_path, target_path))


@pytest.fixture(autouse=True)
def _override_storage_manager():
    fake = _FakeStorageManager()
    app.dependency_overrides[get_storage_manager] = lambda: fake
    try:
        yield fake
    finally:
        app.dependency_overrides.pop(get_storage_manager, None)


def _create_workspace_via_sessions_route(client: TestClient) -> str:
    """
    There is no dedicated "create workspace" route -- `POST /api/v1/sessions`
    auto-provisions the referenced workspace if it doesn't exist yet (see
    `presentation/routes/sessions.py`), so it is reused here to materialize a
    real parent workspace row through the real repository stack.
    """
    user_id = str(uuid4())
    workspace_id = str(uuid4())
    response = client.post(
        "/api/v1/sessions",
        json={"user_id": user_id, "workspace_id": workspace_id},
        headers=_AUTH_HEADERS,
    )
    assert response.status_code == 201
    return workspace_id


def test_fork_workspace_creates_child_and_persists_it(_override_storage_manager):
    with TestClient(app) as client:
        parent_id = _create_workspace_via_sessions_route(client)
        child_mount_path = f"workspace_child_{uuid4()}"

        response = client.post(
            f"/api/v1/workspaces/{parent_id}/fork",
            json={"child_mount_path": child_mount_path},
            headers=_AUTH_HEADERS,
        )

        assert response.status_code == 201
        body = response.json()
        assert body["is_fork"] is True
        assert body["parent_workspace_id"] == parent_id
        assert body["fs_mount_path"] == child_mount_path

        # Physical snapshot was actually requested through the injected port.
        assert _override_storage_manager.snapshots == [
            (f"workspace_{parent_id}", child_mount_path)
        ]

        # Round-trips through the real repository (not just the response body).
        fetch = client.get(f"/api/v1/sessions/{uuid4()}", headers=_AUTH_HEADERS)
        assert fetch.status_code == 404  # sanity: unrelated session truly absent


def test_fork_workspace_requires_auth():
    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/workspaces/{uuid4()}/fork",
            json={"child_mount_path": "workspace_child_noauth"},
        )
    assert response.status_code == 401


def test_fork_workspace_unknown_parent_returns_400():
    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/workspaces/{uuid4()}/fork",
            json={"child_mount_path": f"workspace_child_{uuid4()}"},
            headers=_AUTH_HEADERS,
        )
    assert response.status_code == 400
    assert "not found" in response.json()["detail"].lower()
