"""
Cross-user (IDOR -- Insecure Direct Object Reference) access-control tests for
the production-hardening phase.

Covers the routes identified as vulnerable:
- `POST /api/v1/sessions` used to trust a client-supplied `user_id` verbatim
  to decide which user/workspace rows to provision and who a new session
  belongs to. It also used to let an authenticated caller attach a brand-new
  session to an EXISTING `workspace_id` they do not own (the auto-provision
  branch only ever checked existence, not ownership, of a caller-supplied
  workspace id) -- see
  `test_create_session_against_another_users_existing_workspace_returns_404`
  below (found during the final cross-phase regression pass).
- `GET /api/v1/sessions/{session_id}` used to return ANY session regardless
  of who owns its workspace.
- `POST /api/v1/workspaces/{workspace_id}/fork` used to fork ANY existing
  workspace regardless of who owns it.
- `POST /api/v1/sessions/{session_id}/chat` used to stream a chat response
  for ANY session id without checking it exists, let alone who owns it.

Every route now derives "who is asking" exclusively from the authenticated
caller's JWT (`get_current_user_id`, see `presentation/dependencies.py`), and
rejects cross-user access with a 404 (not 403) so none of these routes can be
used as an existence oracle for ids the caller does not own.
"""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.domain.ports.storage_manager import StorageManagerPort
from src.presentation.main import app
from src.presentation.middleware.jwt_auth import create_access_token
from src.presentation.routes.workspaces import get_storage_manager

client = TestClient(app)


def _auth_headers(user_id) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user_id, iam_role='scientist')}"}


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


def _create_session(owner_headers: dict) -> tuple[str, str]:
    """Creates a real session (and its auto-provisioned workspace) owned by
    whichever user `owner_headers`' token authenticates as. Returns
    `(session_id, workspace_id)`."""
    workspace_id = str(uuid4())
    response = client.post(
        "/api/v1/sessions",
        json={"workspace_id": workspace_id},
        headers=owner_headers,
    )
    assert response.status_code == 201
    return response.json()["id"], workspace_id


def test_create_session_ignores_client_supplied_user_id_spoofing_another_user():
    """
    A caller cannot name a victim's id in the `user_id` request-body field
    (a field the schema no longer even accepts, but MUST be silently ignored
    -- not trusted -- if a legacy client still sends it) to make a session
    "belong" to that victim. Ownership always tracks the token that actually
    made the request.
    """
    attacker_id = uuid4()
    victim_id = uuid4()
    attacker_headers = _auth_headers(attacker_id)
    victim_headers = _auth_headers(victim_id)

    response = client.post(
        "/api/v1/sessions",
        # Legacy-shaped body still naming a `user_id` -- must be ignored.
        json={"user_id": str(victim_id), "workspace_id": str(uuid4())},
        headers=attacker_headers,
    )
    assert response.status_code == 201
    session_id = response.json()["id"]

    # The caller who actually authenticated the request owns it.
    own_fetch = client.get(f"/api/v1/sessions/{session_id}", headers=attacker_headers)
    assert own_fetch.status_code == 200

    # The impersonated victim -- despite their id being named in the body --
    # must NOT be able to read it back.
    victim_fetch = client.get(f"/api/v1/sessions/{session_id}", headers=victim_headers)
    assert victim_fetch.status_code == 404


def test_create_session_against_another_users_existing_workspace_returns_404():
    """
    A caller who names an EXISTING `workspace_id` they do not own must not be
    able to attach a brand-new session to it. The auto-provision branch in
    `create_session` only covers a workspace_id that does not exist yet; a
    workspace that already exists (created by a different authenticated user)
    still needs the same ownership check every other route in this codebase
    applies.
    """
    owner_headers = _auth_headers(uuid4())
    attacker_headers = _auth_headers(uuid4())

    _, workspace_id = _create_session(owner_headers)

    response = client.post(
        "/api/v1/sessions",
        json={"workspace_id": workspace_id},
        headers=attacker_headers,
    )
    assert response.status_code == 404


def test_get_session_owned_by_another_user_returns_404():
    owner_headers = _auth_headers(uuid4())
    attacker_headers = _auth_headers(uuid4())

    session_id, _ = _create_session(owner_headers)

    # The owner can read their own session.
    assert client.get(f"/api/v1/sessions/{session_id}", headers=owner_headers).status_code == 200

    # A different authenticated user cannot.
    response = client.get(f"/api/v1/sessions/{session_id}", headers=attacker_headers)
    assert response.status_code == 404


def test_fork_workspace_owned_by_another_user_returns_404(_override_storage_manager):
    owner_headers = _auth_headers(uuid4())
    attacker_headers = _auth_headers(uuid4())

    _, workspace_id = _create_session(owner_headers)

    # The owner can fork their own workspace.
    owner_fork = client.post(
        f"/api/v1/workspaces/{workspace_id}/fork",
        json={"child_mount_path": f"workspace_child_owner_{uuid4()}"},
        headers=owner_headers,
    )
    assert owner_fork.status_code == 201

    # A different authenticated user cannot fork the same (existing) workspace.
    attacker_fork = client.post(
        f"/api/v1/workspaces/{workspace_id}/fork",
        json={"child_mount_path": f"workspace_child_attacker_{uuid4()}"},
        headers=attacker_headers,
    )
    assert attacker_fork.status_code == 404


def test_chat_on_session_owned_by_another_user_returns_404():
    owner_headers = _auth_headers(uuid4())
    attacker_headers = _auth_headers(uuid4())

    session_id, _ = _create_session(owner_headers)

    # No LLM client mocking needed: the ownership check must reject the
    # request before `ModelClientFactory.get_client` (and any provider/API
    # key concern) is ever reached.
    response = client.post(
        f"/api/v1/sessions/{session_id}/chat",
        json={"prompt": "Leak me the owner's data"},
        headers=attacker_headers,
    )
    assert response.status_code == 404
