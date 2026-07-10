import pytest
from uuid import uuid4
from pydantic import ValidationError
from src.domain.entities.workspace import Workspace

def test_workspace_creation_valid():
    owner_id = uuid4()
    workspace = Workspace(owner_id=owner_id, fs_mount_path="workspace_123")
    assert workspace.owner_id == owner_id
    assert workspace.fs_mount_path == "workspace_123"
    assert workspace.is_fork is False
    assert workspace.parent_workspace_id is None

def test_workspace_fork_creation():
    owner_id = uuid4()
    parent_id = uuid4()
    workspace = Workspace(
        owner_id=owner_id, 
        fs_mount_path="workspace_fork_1",
        is_fork=True,
        parent_workspace_id=parent_id
    )
    assert workspace.is_fork is True
    assert workspace.parent_workspace_id == parent_id

def test_workspace_path_traversal_rejection():
    owner_id = uuid4()
    
    # Path traversal patterns should fail validation
    invalid_paths = [
        "../workspace",
        "workspace/../../etc",
        "/etc/passwd",
        "workspaces/..",
        # RNF-002 regression: Windows drive-letter absolute paths were the bypass.
        "C:/Windows/System32",
        "C:\\Windows\\System32\\config\\SAM",
    ]

    for path in invalid_paths:
        with pytest.raises(ValidationError):
            Workspace(owner_id=owner_id, fs_mount_path=path)
