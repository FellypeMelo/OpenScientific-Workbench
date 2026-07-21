"""
FastAPI dependency providers wiring the Protocol-based domain ports
(`src/domain/ports/`) to their real Postgres-pattern adapter implementations
(`src/infrastructure/persistence/`), each constructed with the request-scoped
`AsyncSession` supplied by `get_db_session`.

Routes should depend on these providers (e.g. `Depends(get_user_repository)`)
instead of importing repository implementations directly, keeping the
presentation layer decoupled from the concrete persistence adapter in use.
"""
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.ports.session_repository import SessionRepositoryPort
from src.domain.ports.user_repository import UserRepositoryPort
from src.domain.ports.workspace_repository import WorkspaceRepositoryPort
from src.infrastructure.persistence.database import get_db_session
from src.infrastructure.persistence.postgres_session_repo import PostgresSessionRepository
from src.infrastructure.persistence.postgres_user_repo import PostgresUserRepository
from src.infrastructure.persistence.postgres_workspace_repo import PostgresWorkspaceRepository


def get_current_user_id(request: Request) -> str:
    """
    Resolve the authenticated caller's user id from the JWT claims that
    `JWTAuthMiddleware` (see `presentation/middleware/jwt_auth.py`) attaches to
    `request.state.user` on every non-allowlisted request, BEFORE any route
    handler runs.

    Security note (IDOR fix): route handlers MUST derive "who is asking" from
    this dependency, never from a client-supplied `user_id`/`owner_id` field in
    a request body or path parameter. Trusting a client-supplied identifier
    there is exactly an Insecure Direct Object Reference hole -- it lets any
    authenticated caller act as, or read data belonging to, an arbitrary other
    user simply by naming their id. This dependency is the single place that
    trust boundary is enforced.

    Defensive-only 401 branch: in practice this is unreachable in normal
    operation -- `JWTAuthMiddleware` always either sets `request.state.user` on
    a valid token or short-circuits the request with its own 401 response
    before any route (and therefore this dependency) ever runs. It exists so a
    route that is accidentally left out of the middleware's coverage (or a
    test app that mounts a route without the middleware) fails loudly with a
    401 instead of silently trusting a forged/absent identity.
    """
    user = getattr(request.state, "user", None)
    if not isinstance(user, dict) or not user.get("sub"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )
    return str(user["sub"])


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
