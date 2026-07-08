"""
FastAPI dependency providers wiring the Protocol-based domain ports
(`src/domain/ports/`) to their real Postgres-pattern adapter implementations
(`src/infrastructure/persistence/`), each constructed with the request-scoped
`AsyncSession` supplied by `get_db_session`.

Routes should depend on these providers (e.g. `Depends(get_user_repository)`)
instead of importing repository implementations directly, keeping the
presentation layer decoupled from the concrete persistence adapter in use.
"""
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.ports.session_repository import SessionRepositoryPort
from src.domain.ports.user_repository import UserRepositoryPort
from src.domain.ports.workspace_repository import WorkspaceRepositoryPort
from src.infrastructure.persistence.database import get_db_session
from src.infrastructure.persistence.postgres_session_repo import PostgresSessionRepository
from src.infrastructure.persistence.postgres_user_repo import PostgresUserRepository
from src.infrastructure.persistence.postgres_workspace_repo import PostgresWorkspaceRepository


def get_user_repository(
    session: AsyncSession = Depends(get_db_session),
) -> UserRepositoryPort:
    return PostgresUserRepository(session)


def get_workspace_repository(
    session: AsyncSession = Depends(get_db_session),
) -> WorkspaceRepositoryPort:
    return PostgresWorkspaceRepository(session)


def get_session_repository(
    session: AsyncSession = Depends(get_db_session),
) -> SessionRepositoryPort:
    return PostgresSessionRepository(session)
