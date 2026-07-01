from uuid import UUID
from src.domain.entities.workspace import Workspace
from src.domain.ports.workspace_repository import WorkspaceRepositoryPort
from src.domain.ports.storage_manager import StorageManagerPort

class ForkWorkspaceUseCase:
    """
    Application use case for making Copy-on-Write (Btrfs/ZFS) workspace forks.
    Provides instant O(1) workspace copies.
    """
    def __init__(
        self,
        workspace_repo: WorkspaceRepositoryPort,
        storage_manager: StorageManagerPort
    ):
        self.workspace_repo = workspace_repo
        self.storage_manager = storage_manager

    async def execute(self, parent_workspace_id: UUID, child_mount_path: str) -> Workspace:
        parent = await self.workspace_repo.get_by_id(parent_workspace_id)
        if not parent:
            raise ValueError(f"Parent workspace {parent_workspace_id} not found.")

        # Create new child workspace record
        child = Workspace(
            owner_id=parent.owner_id,
            fs_mount_path=child_mount_path,
            is_fork=True,
            parent_workspace_id=parent.id
        )

        # Execute the physical zero-copy snapshot on storage
        await self.storage_manager.create_snapshot(
            source_path=parent.fs_mount_path,
            target_path=child.fs_mount_path
        )

        # Save child record
        await self.workspace_repo.save(child)
        return child
