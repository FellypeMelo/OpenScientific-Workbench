from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel
from uuid import UUID
from src.domain.entities.user import User
from src.domain.entities.workspace import Workspace
from src.domain.ports.session_repository import SessionRepositoryPort
from src.domain.ports.user_repository import UserRepositoryPort
from src.domain.ports.workspace_repository import WorkspaceRepositoryPort
from src.application.use_cases.create_session import CreateSessionUseCase
from src.presentation.dependencies import (
    get_current_user_id,
    get_session_repository,
    get_user_repository,
    get_workspace_repository,
)

router = APIRouter(prefix="/sessions", tags=["sessions"])

class CreateSessionRequest(BaseModel):
    # NOTE: deliberately NO `user_id` field (IDOR fix). This request used to
    # accept a client-supplied `user_id` and trust it verbatim to decide which
    # User/Workspace rows to auto-provision and who a new session belongs to --
    # any authenticated caller could pass an arbitrary id and act as/provision
    # data under a different user entirely. The owner is now always the
    # authenticated caller (`get_current_user_id`, see `create_session` below).
    # A client that still sends `user_id` in the body (e.g. the current
    # frontend, see `frontend/src/lib/api-client.ts`) is unaffected: pydantic
    # ignores unknown fields by default, and in the real flow that value is
    # always identical to the caller's authenticated id anyway (see
    # `frontend/src/lib/auth.tsx`).
    workspace_id: UUID

class SessionResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    session_status: str

@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    request: CreateSessionRequest,
    current_user_id: str = Depends(get_current_user_id),
    user_repo: UserRepositoryPort = Depends(get_user_repository),
    workspace_repo: WorkspaceRepositoryPort = Depends(get_workspace_repository),
    session_repo: SessionRepositoryPort = Depends(get_session_repository),
):
    user_id = UUID(current_user_id)

    # Dev convenience: auto-provision the User/Workspace referenced by the caller
    # if they don't exist yet, so a client can start a session without a separate
    # user/workspace registration step. This mirrors the previous in-memory mock
    # behavior, but now persists the records via the real repositories instead of
    # a process-local dict. Values are derived per-id (rather than a single shared
    # literal) because the real schema enforces `UNIQUE` constraints on
    # `users.email` and `workspaces.fs_mount_path`.
    if not await user_repo.get_by_id(user_id):
        await user_repo.save(User(id=user_id, email=f"user-{user_id}@osw.org"))

    existing_workspace = await workspace_repo.get_by_id(request.workspace_id)
    if existing_workspace is None:
        await workspace_repo.save(
            Workspace(
                id=request.workspace_id,
                owner_id=user_id,
                fs_mount_path=f"workspace_{request.workspace_id}",
            )
        )
    elif str(existing_workspace.owner_id) != current_user_id:
        # IDOR fix: an authenticated caller must not be able to attach a new
        # session to a workspace_id someone else already owns just by naming
        # its UUID -- the auto-provision branch above only covers the "does
        # not exist yet" case; a workspace that DOES exist still needs the
        # same ownership check every other route in this codebase applies
        # (`get_session`/`fork_workspace`/`chat_stream`/etc., see
        # `tests/unit/test_idor_ownership.py`). Same 404 (not 403) so this
        # cannot be used as an existence oracle for workspace ids the caller
        # does not own.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")

    use_case = CreateSessionUseCase(
        user_repo=user_repo,
        workspace_repo=workspace_repo,
        session_repo=session_repo
    )
    try:
        session = await use_case.execute(user_id, request.workspace_id)
        return SessionResponse(
            id=session.id,
            workspace_id=session.workspace_id,
            session_status=session.session_status
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: UUID,
    current_user_id: str = Depends(get_current_user_id),
    session_repo: SessionRepositoryPort = Depends(get_session_repository),
    workspace_repo: WorkspaceRepositoryPort = Depends(get_workspace_repository),
):
    session = await session_repo.get_by_id(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # IDOR fix: `AgentSession` has no direct `owner_id` of its own -- ownership
    # is transitive through the workspace it belongs to (see
    # `domain/entities/agent_session.py` / `domain/entities/workspace.py`).
    # A session existing is not enough to return it: the caller must actually
    # own its parent workspace. Responds with the SAME 404 used for "truly
    # doesn't exist" (not a 403) so this endpoint cannot be used as an
    # existence oracle for session ids the caller does not own.
    workspace = await workspace_repo.get_by_id(session.workspace_id)
    if not workspace or str(workspace.owner_id) != current_user_id:
        raise HTTPException(status_code=404, detail="Session not found")

    return SessionResponse(
        id=session.id,
        workspace_id=session.workspace_id,
        session_status=session.session_status
    )
