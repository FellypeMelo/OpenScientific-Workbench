from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel
from uuid import UUID, uuid4
from typing import Dict
from src.domain.entities.user import User
from src.domain.entities.workspace import Workspace
from src.domain.entities.agent_session import AgentSession
from src.application.use_cases.create_session import CreateSessionUseCase
from src.infrastructure.persistence.in_memory_repos import InMemoryUserRepository, InMemoryWorkspaceRepository, InMemorySessionRepository

router = APIRouter(prefix="/sessions", tags=["sessions"])

# Prepopulate mocks for presentation runtime (FastAPI dependencies)
mock_user_repo = InMemoryUserRepository()
mock_workspace_repo = InMemoryWorkspaceRepository()
mock_session_repo = InMemorySessionRepository()

# Setup default user and workspace for test requests
default_user = User(id=uuid4(), email="scientist@osw.org")
default_workspace = Workspace(id=uuid4(), owner_id=default_user.id, fs_mount_path="workspace_1")

class CreateSessionRequest(BaseModel):
    user_id: UUID
    workspace_id: UUID

class SessionResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    session_status: str

@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(request: CreateSessionRequest):
    # Ensure repositories have the requested user/workspace for demonstration
    await mock_user_repo.save(User(id=request.user_id, email="scientist@osw.org"))
    await mock_workspace_repo.save(Workspace(id=request.workspace_id, owner_id=request.user_id, fs_mount_path="test_workspace"))

    use_case = CreateSessionUseCase(
        user_repo=mock_user_repo,
        workspace_repo=mock_workspace_repo,
        session_repo=mock_session_repo
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
async def get_session(session_id: UUID):
    session = await mock_session_repo.get_by_id(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionResponse(
        id=session.id,
        workspace_id=session.workspace_id,
        session_status=session.session_status
    )
