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
    get_session_repository,
    get_user_repository,
    get_workspace_repository,
)

router = APIRouter(prefix="/sessions", tags=["sessions"])

class CreateSessionRequest(BaseModel):
    user_id: UUID
    workspace_id: UUID

class SessionResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    session_status: str

@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    request: CreateSessionRequest,
    user_repo: UserRepositoryPort = Depends(get_user_repository),
    workspace_repo: WorkspaceRepositoryPort = Depends(get_workspace_repository),
    session_repo: SessionRepositoryPort = Depends(get_session_repository),
):
    # Dev convenience: auto-provision the User/Workspace referenced by the caller
    # if they don't exist yet, so a client can start a session without a separate
    # user/workspace registration step. This mirrors the previous in-memory mock
    # behavior, but now persists the records via the real repositories instead of
    # a process-local dict. Values are derived per-id (rather than a single shared
    # literal) because the real schema enforces `UNIQUE` constraints on
    # `users.email` and `workspaces.fs_mount_path`.
    if not await user_repo.get_by_id(request.user_id):
        await user_repo.save(User(id=request.user_id, email=f"user-{request.user_id}@osw.org"))

    if not await workspace_repo.get_by_id(request.workspace_id):
        await workspace_repo.save(
            Workspace(
                id=request.workspace_id,
                owner_id=request.user_id,
                fs_mount_path=f"workspace_{request.workspace_id}",
            )
        )

    use_case = CreateSessionUseCase(
        user_repo=user_repo,
        workspace_repo=workspace_repo,
        session_repo=session_repo
    )
    try:
        session = await use_case.execute(request.user_id, request.workspace_id)
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
    session_repo: SessionRepositoryPort = Depends(get_session_repository),
):
    session = await session_repo.get_by_id(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionResponse(
        id=session.id,
        workspace_id=session.workspace_id,
        session_status=session.session_status
    )
