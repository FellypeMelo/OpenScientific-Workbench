from typing import Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from src.domain.entities.workspace import Workspace
from src.domain.ports.workspace_repository import WorkspaceRepositoryPort
from src.infrastructure.persistence.models import WorkspaceModel

class PostgresWorkspaceRepository(WorkspaceRepositoryPort):
    """
    PostgreSQL adapter implementation for WorkspaceRepositoryPort using SQLAlchemy async session.
    """
    def __init__(self, db_session: AsyncSession):
        self.db_session = db_session

    async def get_by_id(self, workspace_id: UUID) -> Optional[Workspace]:
        result = await self.db_session.execute(
            select(WorkspaceModel).filter(WorkspaceModel.id == workspace_id)
        )
        model = result.scalars().first()
        if not model:
            return None
        return Workspace(
            id=model.id,
            owner_id=model.owner_id,
            fs_mount_path=model.fs_mount_path,
            is_fork=model.is_fork,
            parent_workspace_id=model.parent_workspace_id
        )

    async def save(self, workspace: Workspace) -> None:
        result = await self.db_session.execute(
            select(WorkspaceModel).filter(WorkspaceModel.id == workspace.id)
        )
        model = result.scalars().first()
        
        if model:
            model.fs_mount_path = workspace.fs_mount_path
            model.is_fork = workspace.is_fork
            model.parent_workspace_id = workspace.parent_workspace_id
        else:
            model = WorkspaceModel(
                id=workspace.id,
                owner_id=workspace.owner_id,
                fs_mount_path=workspace.fs_mount_path,
                is_fork=workspace.is_fork,
                parent_workspace_id=workspace.parent_workspace_id
            )
            self.db_session.add(model)
            
        await self.db_session.commit()
