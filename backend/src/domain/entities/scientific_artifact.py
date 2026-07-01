import re
from uuid import UUID, uuid4
from pydantic import BaseModel, Field, field_validator

class ScientificArtifact(BaseModel):
    """
    Domain entity representing a generated scientific artifact (CSV, image, PDF).
    """
    id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    name: str
    sha256_hash: str

    @field_validator("sha256_hash")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        # Regex matching exactly 64 lowercase hexadecimal characters
        pattern = re.compile(r"^[0-9a-f]{64}$")
        if not pattern.match(value):
            raise ValueError("Invalid SHA-256 hash format. Must be 64 lowercase hexadecimal characters.")
        return value
