import pytest
from uuid import uuid4
from typing import Optional, Dict
from src.domain.entities.user import User
from src.domain.entities.workspace import Workspace
from src.domain.entities.agent_session import AgentSession
from src.domain.ports.user_repository import UserRepositoryPort
from src.domain.ports.workspace_repository import WorkspaceRepositoryPort
from src.domain.ports.session_repository import SessionRepositoryPort
from src.application.use_cases.create_session import CreateSessionUseCase

# In-Memory Repository Implementations for Testing Use Cases
class MockUserRepository(UserRepositoryPort):
    def __init__(self):
        self.users: Dict[str, User] = {}
    async def get_by_id(self, user_id) -> Optional[User]:
        return self.users.get(str(user_id))
    async def save(self, user: User) -> None:
        self.users[str(user.id)] = user

class MockWorkspaceRepository(WorkspaceRepositoryPort):
    def __init__(self):
        self.workspaces: Dict[str, Workspace] = {}
    async def get_by_id(self, workspace_id) -> Optional[Workspace]:
        return self.workspaces.get(str(workspace_id))
    async def save(self, workspace: Workspace) -> None:
        self.workspaces[str(workspace.id)] = workspace

class MockSessionRepository(SessionRepositoryPort):
    def __init__(self):
        self.sessions: Dict[str, AgentSession] = {}
    async def get_by_id(self, session_id) -> Optional[AgentSession]:
        return self.sessions.get(str(session_id))
    async def save(self, session: AgentSession) -> None:
        self.sessions[str(session.id)] = session

@pytest.mark.asyncio
async def test_create_session_success():
    user_repo = MockUserRepository()
    workspace_repo = MockWorkspaceRepository()
    session_repo = MockSessionRepository()

    # Prepopulate user and workspace
    user = User(email="test@osw.org")
    await user_repo.save(user)
    
    workspace = Workspace(owner_id=user.id, fs_mount_path="workspace_1")
    await workspace_repo.save(workspace)

    use_case = CreateSessionUseCase(
        user_repo=user_repo,
        workspace_repo=workspace_repo,
        session_repo=session_repo
    )

    session = await use_case.execute(user_id=user.id, workspace_id=workspace.id)
    assert session is not None
    assert session.workspace_id == workspace.id
    assert session.session_status == "INITIALIZING"
    
    # Verify persisted in repo
    persisted = await session_repo.get_by_id(session.id)
    assert persisted is not None
    assert persisted.id == session.id

@pytest.mark.asyncio
async def test_create_session_user_not_found():
    user_repo = MockUserRepository()
    workspace_repo = MockWorkspaceRepository()
    session_repo = MockSessionRepository()

    use_case = CreateSessionUseCase(
        user_repo=user_repo,
        workspace_repo=workspace_repo,
        session_repo=session_repo
    )

    with pytest.raises(ValueError, match="User not found"):
        await use_case.execute(user_id=uuid4(), workspace_id=uuid4())
