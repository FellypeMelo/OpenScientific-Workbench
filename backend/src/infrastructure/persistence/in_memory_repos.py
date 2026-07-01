from typing import Dict, Optional
from uuid import UUID
from src.domain.entities.user import User
from src.domain.entities.workspace import Workspace
from src.domain.entities.agent_session import AgentSession
from src.domain.ports.user_repository import UserRepositoryPort
from src.domain.ports.workspace_repository import WorkspaceRepositoryPort
from src.domain.ports.session_repository import SessionRepositoryPort

class InMemoryUserRepository(UserRepositoryPort):
    def __init__(self):
        self.users: Dict[str, User] = {}
    async def get_by_id(self, user_id: UUID) -> Optional[User]:
        return self.users.get(str(user_id))
    async def save(self, user: User) -> None:
        self.users[str(user.id)] = user

class InMemoryWorkspaceRepository(WorkspaceRepositoryPort):
    def __init__(self):
        self.workspaces: Dict[str, Workspace] = {}
    async def get_by_id(self, workspace_id: UUID) -> Optional[Workspace]:
        return self.workspaces.get(str(workspace_id))
    async def save(self, workspace: Workspace) -> None:
        self.workspaces[str(workspace.id)] = workspace

class InMemorySessionRepository(SessionRepositoryPort):
    def __init__(self):
        self.sessions: Dict[str, AgentSession] = {}
    async def get_by_id(self, session_id: UUID) -> Optional[AgentSession]:
        return self.sessions.get(str(session_id))
    async def save(self, session: AgentSession) -> None:
        self.sessions[str(session.id)] = session
