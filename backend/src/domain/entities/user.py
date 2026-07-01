from uuid import UUID, uuid4
from pydantic import BaseModel, EmailStr, Field

class User(BaseModel):
    """
    Domain entity representing a User.
    """
    id: UUID = Field(default_factory=uuid4)
    email: EmailStr
    iam_role: str = "scientist"

