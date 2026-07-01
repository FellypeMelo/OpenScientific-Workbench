from uuid import UUID, uuid4
from typing import Optional
from pydantic import BaseModel, Field, field_validator

class Workspace(BaseModel):
    """
    Domain entity representing a user's isolated workspace.
    """
    id: UUID = Field(default_factory=uuid4)
    owner_id: UUID
    fs_mount_path: str
    is_fork: bool = False
    parent_workspace_id: Optional[UUID] = None

    @field_validator("fs_mount_path")
    @classmethod
    def validate_mount_path(cls, value: str) -> str:
        # Strip trailing/leading whitespace
        cleaned = value.strip()
        
        # Check for path traversal attempts (CWE-22 / CVE-2026-7398)
        if ".." in cleaned or cleaned.startswith("/") or cleaned.startswith("\\"):
            raise ValueError("Secure sandbox violation: Absolute paths or path traversal (..) are not allowed.")
            
        return cleaned
