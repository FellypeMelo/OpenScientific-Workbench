from typing import Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from src.domain.entities.agent_session import AgentSession
from src.domain.ports.session_repository import SessionRepositoryPort
from src.infrastructure.persistence.models import AgentSessionModel

class PostgresSessionRepository(SessionRepositoryPort):
    """
    PostgreSQL adapter implementation for SessionRepositoryPort using SQLAlchemy async session.
    """
    def __init__(self, db_session: AsyncSession):
        self.db_session = db_session

    async def get_by_id(self, session_id: UUID) -> Optional[AgentSession]:
        result = await self.db_session.execute(
            select(AgentSessionModel).filter(AgentSessionModel.id == session_id)
        )
        model = result.scalars().first()
        if not model:
            return None
        return AgentSession(
            id=model.id,
            workspace_id=model.workspace_id,
            session_status=model.session_status,
            dag_snapshot=model.dag_snapshot,
            provenance_log=model.provenance_log,
            dag_generation_attempts=model.dag_generation_attempts
        )

    async def save(self, session: AgentSession) -> None:
        # Check if record already exists to perform update
        result = await self.db_session.execute(
            select(AgentSessionModel).filter(AgentSessionModel.id == session.id)
        )
        model = result.scalars().first()
        
        if model:
            model.session_status = session.session_status
            model.dag_snapshot = session.dag_snapshot
            model.provenance_log = session.provenance_log
            model.dag_generation_attempts = session.dag_generation_attempts
        else:
            model = AgentSessionModel(
                id=session.id,
                workspace_id=session.workspace_id,
                session_status=session.session_status,
                dag_snapshot=session.dag_snapshot,
                provenance_log=session.provenance_log,
                dag_generation_attempts=session.dag_generation_attempts
            )
            self.db_session.add(model)
            
        await self.db_session.commit()
