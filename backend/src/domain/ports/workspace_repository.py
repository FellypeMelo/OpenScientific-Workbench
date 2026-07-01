from typing import Protocol, Optional
from uuid import UUID
from src.domain.entities.workspace import Workspace

class WorkspaceRepositoryPort(Protocol):
    """
    Domain port interface for Workspace persistence operations.
    """
    async def get_by_id(self, workspace_id: UUID) -> Optional[Workspace]:
        ...

    async def save(self, workspace: Workspace) -> None:
        ...
