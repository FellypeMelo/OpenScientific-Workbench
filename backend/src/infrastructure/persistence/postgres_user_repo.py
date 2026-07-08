from typing import Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from src.domain.entities.user import User
from src.domain.ports.user_repository import UserRepositoryPort
from src.infrastructure.persistence.models import UserModel

class PostgresUserRepository(UserRepositoryPort):
    """
    PostgreSQL adapter implementation for UserRepositoryPort using SQLAlchemy async session.
    """
    def __init__(self, db_session: AsyncSession):
        self.db_session = db_session

    async def get_by_id(self, user_id: UUID) -> Optional[User]:
        result = await self.db_session.execute(
            select(UserModel).filter(UserModel.id == user_id)
        )
        model = result.scalars().first()
        if not model:
            return None
        return User(
            id=model.id,
            email=model.email,
            iam_role=model.iam_role
        )

    async def save(self, user: User) -> None:
        # Check if record already exists to perform update
        result = await self.db_session.execute(
            select(UserModel).filter(UserModel.id == user.id)
        )
        model = result.scalars().first()

        if model:
            model.email = user.email
            model.iam_role = user.iam_role
        else:
            model = UserModel(
                id=user.id,
                email=user.email,
                iam_role=user.iam_role
            )
            self.db_session.add(model)

        await self.db_session.commit()
