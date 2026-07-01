import pytest
from uuid import uuid4
from src.domain.entities.workspace import Workspace
from src.domain.ports.storage_manager import StorageManagerPort
from tests.unit.test_create_session import MockWorkspaceRepository
from src.application.use_cases.fork_workspace import ForkWorkspaceUseCase

class MockStorageManager(StorageManagerPort):
    def __init__(self):
        self.snapshots = []
    async def create_snapshot(self, source_path: str, target_path: str) -> None:
        self.snapshots.append((source_path, target_path))

@pytest.mark.asyncio
async def test_fork_workspace_success():
    workspace_repo = MockWorkspaceRepository()
    storage_manager = MockStorageManager()

    parent = Workspace(owner_id=uuid4(), fs_mount_path="workspace_parent")
    await workspace_repo.save(parent)

    use_case = ForkWorkspaceUseCase(
        workspace_repo=workspace_repo,
        storage_manager=storage_manager
    )

    child = await use_case.execute(parent_workspace_id=parent.id, child_mount_path="workspace_child")
    assert child is not None
    assert child.is_fork is True
    assert child.parent_workspace_id == parent.id
    assert child.fs_mount_path == "workspace_child"

    # Verify physical snapshot was requested
    assert len(storage_manager.snapshots) == 1
    assert storage_manager.snapshots[0] == ("workspace_parent", "workspace_child")

    # Verify persisted
    persisted = await workspace_repo.get_by_id(child.id)
    assert persisted is not None
    assert persisted.id == child.id
