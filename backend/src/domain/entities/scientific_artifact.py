import re
from uuid import UUID, uuid4
from pydantic import BaseModel, Field, field_validator

from src.domain.services.reproducibility import compute_lockfile_hash

class ScientificArtifact(BaseModel):
    """
    Domain entity representing a generated scientific artifact (CSV, image, PDF).
    """
    id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    name: str
    sha256_hash: str

    @classmethod
    def from_generated_output(
        cls, session_id: UUID, name: str, lockfile_path: str
    ) -> "ScientificArtifact":
        """Build an artifact whose ``sha256_hash`` is derived from the dependency
        lockfile (RNF-006), guaranteeing provenance instead of accepting an
        arbitrary caller-supplied hash string."""
        return cls(
            session_id=session_id,
            name=name,
            sha256_hash=compute_lockfile_hash(lockfile_path),
        )

    @field_validator("sha256_hash")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        # Regex matching exactly 64 lowercase hexadecimal characters
        pattern = re.compile(r"^[0-9a-f]{64}$")
        if not pattern.match(value):
            raise ValueError("Invalid SHA-256 hash format. Must be 64 lowercase hexadecimal characters.")
        return value
