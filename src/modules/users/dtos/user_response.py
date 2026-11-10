from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr

from src.common.constants.enums import UserRole


class UserResponse(BaseModel):
    """Full profile - only ever returned to the owner or an admin."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    username: str
    role: UserRole
    is_active: bool
    created_at: datetime


class PublicUserResponse(BaseModel):
    """Minimal identity safe to expose to other users."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str
