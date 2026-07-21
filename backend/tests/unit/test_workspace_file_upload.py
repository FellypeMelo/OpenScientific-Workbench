"""Unit tests for `POST /api/v1/workspaces/{workspace_id}/files`
(`presentation/routes/workspaces.py`), the RF-005 gap-closure file-upload
endpoint.

Goes through the real DB-backed `WorkspaceRepositoryPort` (via the autouse
`_isolated_test_database` fixture in `conftest.py`) and writes REAL files to
disk under the same `workspace_<id>/` convention `routes/sessions.py` already
uses -- gitignored at the repo root (`workspace_*/`), same pattern
`test_infrastructure_adapters.py::test_btrfs_snapshot_manager_fallback` uses
for its own real-filesystem test, cleaned up in a `finally` block.
"""
import io
import os
import shutil
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.infrastructure.config import settings
from src.presentation.main import app
from src.presentation.middleware.jwt_auth import create_access_token

_AUTH_HEADERS = {"Authorization": f"Bearer {create_access_token(uuid4(), iam_role='scientist')}"}


def _create_workspace(client: TestClient) -> str:
    workspace_id = str(uuid4())
    response = client.post(
        "/api/v1/sessions",
        json={"workspace_id": workspace_id},
        headers=_AUTH_HEADERS,
    )
    assert response.status_code == 201
    return workspace_id


@pytest.fixture
def _cleanup_workspace_dirs():
    created = []
    yield created
    for workspace_id in created:
        shutil.rmtree(f"workspace_{workspace_id}", ignore_errors=True)


def test_upload_file_writes_real_file_under_workspace_root(_cleanup_workspace_dirs):
    with TestClient(app) as client:
        workspace_id = _create_workspace(client)
        _cleanup_workspace_dirs.append(workspace_id)

        response = client.post(
            f"/api/v1/workspaces/{workspace_id}/files",
            files={"file": ("data.csv", io.BytesIO(b"a,b\n1,2\n"), "text/csv")},
            headers=_AUTH_HEADERS,
        )

        assert response.status_code == 201
        body = response.json()
        assert body["relative_path"] == "data.csv"
        assert body["size_bytes"] == len(b"a,b\n1,2\n")

        written = os.path.join(f"workspace_{workspace_id}", "data.csv")
        assert os.path.exists(written)
        with open(written, "rb") as fh:
            assert fh.read() == b"a,b\n1,2\n"


def test_upload_file_honours_relative_path_directory(_cleanup_workspace_dirs):
    with TestClient(app) as client:
        workspace_id = _create_workspace(client)
        _cleanup_workspace_dirs.append(workspace_id)

        response = client.post(
            f"/api/v1/workspaces/{workspace_id}/files",
            data={"relative_path": "inputs/nested"},
            files={"file": ("genome.fa", io.BytesIO(b">seq1\nACGT\n"), "text/plain")},
            headers=_AUTH_HEADERS,
        )

        assert response.status_code == 201
        assert response.json()["relative_path"] == "inputs/nested/genome.fa"

        written = os.path.join(f"workspace_{workspace_id}", "inputs", "nested", "genome.fa")
        assert os.path.exists(written)


def test_upload_file_sanitizes_path_traversal_filename(_cleanup_workspace_dirs):
    """Starlette does NOT sanitize `UploadFile.filename` -- a malicious
    filename must be reduced to its basename before touching the filesystem,
    never allowed to escape the workspace root."""
    with TestClient(app) as client:
        workspace_id = _create_workspace(client)
        _cleanup_workspace_dirs.append(workspace_id)

        response = client.post(
            f"/api/v1/workspaces/{workspace_id}/files",
            files={"file": ("../../evil.sh", io.BytesIO(b"malicious"), "text/plain")},
            headers=_AUTH_HEADERS,
        )

        assert response.status_code == 201
        assert response.json()["relative_path"] == "evil.sh"

        # Landed INSIDE the workspace root, not two levels above it.
        written = os.path.join(f"workspace_{workspace_id}", "evil.sh")
        assert os.path.exists(written)
        assert not os.path.exists(os.path.join("..", "evil.sh"))
        assert not os.path.exists("evil.sh")


def test_upload_file_rejects_traversal_in_relative_path(_cleanup_workspace_dirs):
    with TestClient(app) as client:
        workspace_id = _create_workspace(client)
        _cleanup_workspace_dirs.append(workspace_id)

        response = client.post(
            f"/api/v1/workspaces/{workspace_id}/files",
            data={"relative_path": "../../etc"},
            files={"file": ("passwd", io.BytesIO(b"x"), "text/plain")},
            headers=_AUTH_HEADERS,
        )

        assert response.status_code == 400


def test_upload_file_requires_auth():
    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/workspaces/{uuid4()}/files",
            files={"file": ("data.csv", io.BytesIO(b"x"), "text/csv")},
        )
    assert response.status_code == 401


def test_upload_file_nonexistent_workspace_returns_404():
    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/workspaces/{uuid4()}/files",
            files={"file": ("data.csv", io.BytesIO(b"x"), "text/csv")},
            headers=_AUTH_HEADERS,
        )
    assert response.status_code == 404


def test_upload_file_not_owner_returns_404(_cleanup_workspace_dirs):
    with TestClient(app) as client:
        workspace_id = _create_workspace(client)
        _cleanup_workspace_dirs.append(workspace_id)

        other_headers = {"Authorization": f"Bearer {create_access_token(uuid4(), iam_role='scientist')}"}
        response = client.post(
            f"/api/v1/workspaces/{workspace_id}/files",
            files={"file": ("data.csv", io.BytesIO(b"x"), "text/csv")},
            headers=other_headers,
        )
    assert response.status_code == 404


def test_upload_file_over_size_cap_returns_413_and_cleans_up(_cleanup_workspace_dirs, monkeypatch):
    monkeypatch.setattr(settings, "MAX_UPLOAD_MB", 1)

    with TestClient(app) as client:
        workspace_id = _create_workspace(client)
        _cleanup_workspace_dirs.append(workspace_id)

        oversized = b"x" * (2 * 1024 * 1024)
        response = client.post(
            f"/api/v1/workspaces/{workspace_id}/files",
            files={"file": ("big.bin", io.BytesIO(oversized), "application/octet-stream")},
            headers=_AUTH_HEADERS,
        )

        assert response.status_code == 413
        written = os.path.join(f"workspace_{workspace_id}", "big.bin")
        assert not os.path.exists(written)
