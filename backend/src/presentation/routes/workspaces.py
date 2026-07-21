from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from src.application.use_cases.fork_workspace import ForkWorkspaceUseCase
from src.domain.ports.storage_manager import StorageManagerPort
from src.domain.ports.workspace_repository import WorkspaceRepositoryPort
from src.infrastructure.config import settings
from src.infrastructure.storage.btrfs_manager import BtrfsSnapshotManager
from src.presentation.dependencies import get_current_user_id, get_workspace_repository

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


def get_storage_manager() -> StorageManagerPort:
    # Honour the USE_BTRFS config flag (RNF-007) so a real Btrfs host can enable
    # CoW forks. `use_btrfs` still self-disables on non-Linux platforms (see
    # `BtrfsSnapshotManager.__init__`), falling back to a real recursive
    # directory copy -- so this is safe on a Windows/dev/CI box too.
    return BtrfsSnapshotManager(use_btrfs=settings.USE_BTRFS)


class ForkWorkspaceRequest(BaseModel):
    child_mount_path: str


class WorkspaceResponse(BaseModel):
    id: UUID
    owner_id: UUID
    fs_mount_path: str
    is_fork: bool
    parent_workspace_id: Optional[UUID] = None


@router.post(
    "/{workspace_id}/fork",
    response_model=WorkspaceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def fork_workspace(
    workspace_id: UUID,
    request: ForkWorkspaceRequest,
    current_user_id: str = Depends(get_current_user_id),
    workspace_repo: WorkspaceRepositoryPort = Depends(get_workspace_repository),
    storage_manager: StorageManagerPort = Depends(get_storage_manager),
) -> WorkspaceResponse:
    # IDOR fix: forking is only allowed on a workspace the caller actually
    # owns. When the parent exists but belongs to someone else, respond with
    # the SAME 404 used for "truly doesn't exist" (not 403/400) so this route
    # cannot be used as an existence oracle for workspace ids the caller does
    # not own. A genuinely missing parent still falls through to
    # `ForkWorkspaceUseCase`, preserving the existing 400 "not found" behavior
    # for that case.
    parent = await workspace_repo.get_by_id(workspace_id)
    if parent is not None and str(parent.owner_id) != current_user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")

    use_case = ForkWorkspaceUseCase(workspace_repo=workspace_repo, storage_manager=storage_manager)
    try:
        child = await use_case.execute(
            parent_workspace_id=workspace_id,
            child_mount_path=request.child_mount_path,
        )
    except ValueError as exc:
        # Mirrors the convention already established in `routes/sessions.py`:
        # a domain-level `ValueError` (e.g. "parent workspace not found") maps
        # to a 400, not a 404 -- the request itself references an invalid/
        # nonexistent parent, which this codebase treats as a bad request.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except (FileNotFoundError, NotADirectoryError) as exc:
        # Raised by `BtrfsSnapshotManager.create_snapshot` when the parent
        # workspace's `fs_mount_path` isn't materialized on disk -- a real
        # bug/inconsistency between the DB record and the filesystem, not a
        # client input error, but still not worth a raw 500.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return WorkspaceResponse(
        id=child.id,
        owner_id=child.owner_id,
        fs_mount_path=child.fs_mount_path,
        is_fork=child.is_fork,
        parent_workspace_id=child.parent_workspace_id,
    )
