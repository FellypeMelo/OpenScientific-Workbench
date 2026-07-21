import os
import posixpath
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status
from pydantic import BaseModel

from src.application.use_cases.fork_workspace import ForkWorkspaceUseCase
from src.domain.ports.storage_manager import StorageManagerPort
from src.domain.ports.workspace_repository import WorkspaceRepositoryPort
from src.domain.services.path_guard import PathTraversalError, ensure_safe_relative_path
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


class FileUploadResponse(BaseModel):
    relative_path: str
    size_bytes: int


# Bounded chunked read size for `upload_file` below -- large enough to be
# efficient, small enough that the `MAX_UPLOAD_MB` cap check below can never
# let a single read balloon memory far past that cap before catching it.
_UPLOAD_CHUNK_BYTES = 1024 * 1024


@router.post(
    "/{workspace_id}/files",
    response_model=FileUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_file(
    workspace_id: UUID,
    file: UploadFile,
    # Caller-chosen destination DIRECTORY inside the workspace (e.g.
    # "data/inputs"); the uploaded file's own (sanitized) basename is appended
    # to it -- see the two-stage validation below. Optional: "" uploads
    # directly into the workspace root.
    relative_path: str = Form(""),
    current_user_id: str = Depends(get_current_user_id),
    workspace_repo: WorkspaceRepositoryPort = Depends(get_workspace_repository),
) -> FileUploadResponse:
    # IDOR fix, same pattern as `fork_workspace` above: only the owner may
    # upload into their own workspace, and a workspace that doesn't exist or
    # isn't owned by the caller 404s identically so this route cannot be used
    # as an existence oracle.
    workspace = await workspace_repo.get_by_id(workspace_id)
    if not workspace or str(workspace.owner_id) != current_user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")

    # 1. Validate the caller-supplied destination directory through the same
    #    containment guard used everywhere else in this codebase (RNF-002).
    try:
        safe_dir = ensure_safe_relative_path(relative_path) if relative_path.strip() else ""
    except PathTraversalError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    # 2. SEPARATELY sanitize the raw upload filename: Starlette/FastAPI do NOT
    #    sanitize `UploadFile.filename` (it is attacker-controlled multipart
    #    metadata), so a filename of e.g. "../../evil.sh" must be reduced to
    #    just "evil.sh" before it is ever joined onto a filesystem path --
    #    `ensure_safe_relative_path` above only validated `relative_path`, not
    #    this independent, differently-sourced value.
    raw_name = (file.filename or "upload.bin").replace("\\", "/")
    safe_name = os.path.basename(raw_name)
    if not safe_name or safe_name in (".", ".."):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid upload filename.")

    dest_relative = posixpath.join(safe_dir, safe_name) if safe_dir else safe_name

    # 3. Defense in depth: resolve the FINAL path with `os.path.realpath` and
    #    verify it still sits under the workspace root, even though steps 1-2
    #    should already guarantee that -- catches anything those two checks
    #    individually couldn't (e.g. a symlink planted inside the workspace).
    workspace_root_abs = os.path.realpath(workspace.fs_mount_path)
    final_path = os.path.realpath(os.path.join(workspace_root_abs, dest_relative))
    if final_path != workspace_root_abs and not final_path.startswith(workspace_root_abs + os.sep):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Resolved upload path escapes the workspace root.",
        )

    os.makedirs(os.path.dirname(final_path), exist_ok=True)

    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
    total_bytes = 0
    try:
        with open(final_path, "wb") as out:
            while True:
                chunk = await file.read(_UPLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > max_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"Upload exceeds MAX_UPLOAD_MB={settings.MAX_UPLOAD_MB}.",
                    )
                out.write(chunk)
    except HTTPException:
        # Don't leave a truncated partial file behind on a rejected upload.
        if os.path.exists(final_path):
            os.remove(final_path)
        raise
    finally:
        await file.close()

    return FileUploadResponse(relative_path=dest_relative, size_bytes=total_bytes)
