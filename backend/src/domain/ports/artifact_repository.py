from typing import Protocol, Optional
from uuid import UUID
from src.domain.entities.scientific_artifact import ScientificArtifact

class ArtifactRepositoryPort(Protocol):
    """
    Domain port interface for ScientificArtifact persistence operations.
    """
    async def get_by_id(self, artifact_id: UUID) -> Optional[ScientificArtifact]:
        ...

    async def save(self, artifact: ScientificArtifact) -> None:
        ...
