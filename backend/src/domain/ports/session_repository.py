from typing import Protocol, Optional
from uuid import UUID
from src.domain.entities.agent_session import AgentSession

class SessionRepositoryPort(Protocol):
    """
    Domain port interface for AgentSession persistence operations.
    """
    async def get_by_id(self, session_id: UUID) -> Optional[AgentSession]:
        ...

    async def save(self, session: AgentSession) -> None:
        ...
