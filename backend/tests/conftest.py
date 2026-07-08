"""
Shared test fixtures for the backend suite.

Every test that exercises the FastAPI app (via `TestClient`) now goes through real
Postgres-pattern repositories (`src/infrastructure/persistence/postgres_*_repo.py`)
instead of the old in-memory mocks. To keep the suite hermetic -- no test should
depend on, or leave residue in, the local dev SQLite file configured by
`settings.DATABASE_URL` -- this fixture transparently redirects the
`get_db_session` FastAPI dependency to an isolated, file-backed SQLite database
for the duration of each test.

Why a *file* (not `sqlite+aiosqlite:///:memory:`) and why a *fresh engine per call*
instead of one cached engine/sessionmaker:
`starlette.testclient.TestClient`, when not entered as a context manager
(`with TestClient(app) as client: ...`), spins up a brand new thread + event loop
for *every single HTTP call* (see `TestClient._portal_factory`). SQLAlchemy's async
engine/pool binds internal asyncio primitives to whichever event loop first used
them, so reusing one `AsyncEngine`/pooled connection object across two calls that
each ran in a different ephemeral loop raises "Task/Future attached to a different
loop" errors. Some existing/allowed tests in this suite use a bare
`TestClient(app)` (no `with`), so the override must tolerate that pattern.
Creating a brand new engine per dependency call sidesteps the cross-loop hazard
entirely (nothing is ever reused across loops); using a file-backed SQLite
database (instead of an in-memory one) keeps the data consistent across those
disposable engine instances because the state lives on disk, not inside any
particular engine/connection object.
"""
from typing import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.infrastructure.persistence.database import get_db_session
from src.infrastructure.persistence.models import Base
from src.presentation.main import app


@pytest.fixture(autouse=True)
async def _isolated_test_database(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("osw-db") / "test.db"
    db_url = f"sqlite+aiosqlite:///{db_path}"

    # Bootstrap the schema once up front, on a throwaway engine/connection that is
    # fully created and disposed within this fixture's own event loop.
    bootstrap_engine = create_async_engine(db_url, future=True)
    async with bootstrap_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await bootstrap_engine.dispose()

    async def _override_get_db_session() -> AsyncGenerator[AsyncSession, None]:
        # Deliberately not cached at fixture scope -- see module docstring.
        request_engine = create_async_engine(db_url, future=True)
        request_sessionmaker = async_sessionmaker(
            bind=request_engine, class_=AsyncSession, expire_on_commit=False
        )
        try:
            async with request_sessionmaker() as session:
                try:
                    yield session
                except Exception:
                    await session.rollback()
                    raise
                finally:
                    await session.close()
        finally:
            await request_engine.dispose()

    app.dependency_overrides[get_db_session] = _override_get_db_session
    try:
        yield db_url
    finally:
        app.dependency_overrides.pop(get_db_session, None)
