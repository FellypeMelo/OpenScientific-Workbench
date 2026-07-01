from uuid import UUID
from src.domain.entities.agent_session import AgentSession
from src.domain.ports.user_repository import UserRepositoryPort
from src.domain.ports.workspace_repository import WorkspaceRepositoryPort
from src.domain.ports.session_repository import SessionRepositoryPort

class CreateSessionUseCase:
    """
    Application service that orchestrates the creation of a new research agent session.
    """
    def __init__(
        self,
        user_repo: UserRepositoryPort,
        workspace_repo: WorkspaceRepositoryPort,
        session_repo: SessionRepositoryPort
    ):
        self.user_repo = user_repo
        self.workspace_repo = workspace_repo
        self.session_repo = session_repo

    async def execute(self, user_id: UUID, workspace_id: UUID) -> AgentSession:
        # 1. Validate user existence
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise ValueError("User not found: Authorized user account is required to start a session.")

        # 2. Validate workspace existence
        workspace = await self.workspace_repo.get_by_id(workspace_id)
        if not workspace:
            raise ValueError("Workspace not found: Authorized mount workspace is required to start a session.")

        # 3. Create and persist the session
        session = AgentSession(workspace_id=workspace_id)
        await self.session_repo.save(session)
        
        return session
