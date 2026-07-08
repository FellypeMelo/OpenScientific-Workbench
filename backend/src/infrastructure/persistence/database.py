"""
Async SQLAlchemy engine/session wiring backing the application's relational
persistence layer (Fase 1 - Postgres wiring).

This module owns the single, process-wide `AsyncEngine` bound to
`settings.DATABASE_URL` (Postgres in staging/production, local SQLite file for dev),
plus the `async_sessionmaker` used to hand out request-scoped `AsyncSession`
instances via the `get_db_session` FastAPI dependency.

Design notes:
- Constructing `AsyncEngine`/`async_sessionmaker` does not open a connection or
  require a running event loop; the underlying DBAPI connection/pool is only
  established lazily on first use, inside whichever event loop is active at that
  point (the request's loop in a real deployment). This keeps the module safe to
  import anywhere (including at FastAPI app import time) without needing an
  `asyncio` context.
- No Alembic migrations exist yet, so `init_models()` (a thin wrapper around
  `Base.metadata.create_all`) is used to bootstrap tables for local dev/tests. A
  real migration tool should replace this before production rollout with Postgres.
"""
from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from src.infrastructure.config import settings
from src.infrastructure.persistence.models import Base

# Module-level singleton engine/sessionmaker, mirroring the `settings` singleton
# pattern used across the codebase (see `src/infrastructure/config.py`).
engine: AsyncEngine = create_async_engine(settings.DATABASE_URL, echo=False, future=True)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that yields a request-scoped `AsyncSession`.

    The session is rolled back on any unhandled exception raised while the request
    is being processed, and is always closed (returning its connection to the pool)
    once the request finishes, regardless of outcome.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_models(bind_engine: Optional[AsyncEngine] = None) -> None:
    """
    Create all ORM tables declared on `Base.metadata` (dev/test bootstrap).

    Defaults to the module-level `engine`, but accepts an explicit `bind_engine`
    so callers (e.g. tests wiring up an isolated SQLite database) can reuse this
    helper against a different engine instance.
    """
    target_engine = bind_engine or engine
    async with target_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
