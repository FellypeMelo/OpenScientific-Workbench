from typing import Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from src.domain.entities.scientific_artifact import ScientificArtifact
from src.domain.ports.artifact_repository import ArtifactRepositoryPort
from src.infrastructure.persistence.models import ArtifactModel

class PostgresArtifactRepository(ArtifactRepositoryPort):
    """
    PostgreSQL adapter implementation for ArtifactRepositoryPort using SQLAlchemy async session.
    """
    def __init__(self, db_session: AsyncSession):
        self.db_session = db_session

    async def get_by_id(self, artifact_id: UUID) -> Optional[ScientificArtifact]:
        result = await self.db_session.execute(
            select(ArtifactModel).filter(ArtifactModel.id == artifact_id)
        )
        model = result.scalars().first()
        if not model:
            return None
        return ScientificArtifact(
            id=model.id,
            session_id=model.session_id,
            name=model.name,
            sha256_hash=model.sha256_hash,
        )

    async def save(self, artifact: ScientificArtifact) -> None:
        result = await self.db_session.execute(
            select(ArtifactModel).filter(ArtifactModel.id == artifact.id)
        )
        model = result.scalars().first()

        if model:
            model.session_id = artifact.session_id
            model.name = artifact.name
            model.sha256_hash = artifact.sha256_hash
        else:
            model = ArtifactModel(
                id=artifact.id,
                session_id=artifact.session_id,
                name=artifact.name,
                sha256_hash=artifact.sha256_hash,
            )
            self.db_session.add(model)

        await self.db_session.commit()
