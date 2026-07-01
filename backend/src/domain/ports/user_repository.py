from typing import Protocol, Optional
from uuid import UUID
from src.domain.entities.user import User

class UserRepositoryPort(Protocol):
    """
    Domain port interface for User persistence operations.
    """
    async def get_by_id(self, user_id: UUID) -> Optional[User]:
        ...

    async def save(self, user: User) -> None:
        ...
