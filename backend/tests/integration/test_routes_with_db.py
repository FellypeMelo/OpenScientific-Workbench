"""
Integration coverage for the `/api/v1/sessions` routes wired to the real
Postgres-pattern repositories (`PostgresUserRepository`, `PostgresWorkspaceRepository`,
`PostgresSessionRepository`) instead of the old in-memory mocks.

The `get_db_session` FastAPI dependency is transparently redirected to an isolated,
file-backed SQLite database by the autouse `_isolated_test_database` fixture in
`tests/conftest.py` (via `app.dependency_overrides`), so this test never touches a
real Postgres server nor the local dev SQLite file.
"""
import pytest
from fastapi.testclient import TestClient
from uuid import uuid4

from src.presentation.main import app
from src.infrastructure.persistence.models import UserModel, WorkspaceModel, AgentSessionModel
from src.presentation.middleware.jwt_auth import create_access_token

# Every route is now behind the globally-registered JWT auth middleware (Fase 2).
# There is no login endpoint yet, so tests mint their own token via the same helper
# the middleware ships for this purpose -- see `presentation/middleware/jwt_auth.py`.
_AUTH_HEADERS = {"Authorization": f"Bearer {create_access_token(uuid4(), iam_role='scientist')}"}


def test_create_then_fetch_session_round_trips_through_real_repositories():
    user_id = uuid4()
    workspace_id = uuid4()

    # `with` enters the app's lifespan (startup/shutdown) and keeps the TestClient's
    # single background event loop alive for every request made inside the block.
    with TestClient(app) as client:
        create_response = client.post(
            "/api/v1/sessions",
            json={"user_id": str(user_id), "workspace_id": str(workspace_id)},
            headers=_AUTH_HEADERS,
        )
        assert create_response.status_code == 201
        created = create_response.json()
        assert created["workspace_id"] == str(workspace_id)
        assert created["session_status"] == "INITIALIZING"

        session_id = created["id"]

        fetch_response = client.get(f"/api/v1/sessions/{session_id}", headers=_AUTH_HEADERS)
        assert fetch_response.status_code == 200
        fetched = fetch_response.json()

        # Round-trips exactly as returned at creation time -- proves the session was
        # actually persisted (and re-read) via the real repository/ORM stack rather
        # than an in-memory dict local to the request.
        assert fetched == created


def test_get_session_not_found_returns_404():
    with TestClient(app) as client:
        response = client.get(f"/api/v1/sessions/{uuid4()}", headers=_AUTH_HEADERS)
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_session_persists_user_and_workspace_rows(_isolated_test_database):
    """
    Asserts the dev-convenience auto-provisioning of the caller's user/workspace
    actually lands rows in the ORM tables (not just an in-memory dict), by opening
    a fresh session against the very same isolated SQLite file the route used.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.future import select

    user_id = uuid4()
    workspace_id = uuid4()

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/sessions",
            json={"user_id": str(user_id), "workspace_id": str(workspace_id)},
            headers=_AUTH_HEADERS,
        )
        assert response.status_code == 201

    verify_engine = create_async_engine(_isolated_test_database, future=True)
    verify_sessionmaker = async_sessionmaker(bind=verify_engine, class_=AsyncSession, expire_on_commit=False)
    async with verify_sessionmaker() as session:
        user_row = (
            await session.execute(select(UserModel).filter(UserModel.id == user_id))
        ).scalars().first()
        workspace_row = (
            await session.execute(select(WorkspaceModel).filter(WorkspaceModel.id == workspace_id))
        ).scalars().first()
        session_row = (
            await session.execute(
                select(AgentSessionModel).filter(AgentSessionModel.workspace_id == workspace_id)
            )
        ).scalars().first()

    await verify_engine.dispose()

    assert user_row is not None
    assert workspace_row is not None
    assert session_row is not None
    assert session_row.session_status == "INITIALIZING"
