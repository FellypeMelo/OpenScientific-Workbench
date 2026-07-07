import pytest
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from src.infrastructure.persistence.database import get_db_session, init_models


@pytest.mark.asyncio
async def test_get_db_session_yields_a_working_session_and_closes_cleanly():
    gen = get_db_session()
    session = await gen.__anext__()

    result = await session.execute(text("SELECT 1"))
    assert result.scalar() == 1

    # Draining the generator normally simulates FastAPI completing the request
    # lifecycle: the `finally: await session.close()` branch must run without error.
    with pytest.raises(StopAsyncIteration):
        await gen.__anext__()


@pytest.mark.asyncio
async def test_get_db_session_rolls_back_and_reraises_on_exception():
    gen = get_db_session()
    await gen.__anext__()

    class _SimulatedFailure(Exception):
        pass

    # Simulates an unhandled exception occurring mid-request (e.g. a repository
    # raising while using the yielded session); the dependency must roll back and
    # propagate the original exception rather than swallowing it.
    with pytest.raises(_SimulatedFailure):
        await gen.athrow(_SimulatedFailure("simulated failure mid-request"))


@pytest.mark.asyncio
async def test_init_models_creates_tables_on_an_explicit_engine():
    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    try:
        await init_models(test_engine)

        async with test_engine.connect() as conn:
            table_names = await conn.run_sync(lambda sync_conn: sa_inspect(sync_conn).get_table_names())

        assert {"users", "workspaces", "agent_sessions"}.issubset(set(table_names))
    finally:
        await test_engine.dispose()
