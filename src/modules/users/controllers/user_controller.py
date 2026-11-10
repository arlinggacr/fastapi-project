"""User routes: /users/*"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.session import get_session
from src.modules.users.dtos.user_response import PublicUserResponse, UserResponse
from src.modules.users.entities.user import User
from src.modules.users.services.user_service import UserService
from src.utils.deps import get_current_user

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserResponse)
async def read_me(user: User = Depends(get_current_user)) -> User:
    return user


@router.get("/{user_id}", response_model=PublicUserResponse)
async def read_user(
    user_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> User:
    return await UserService(session).get(user_id)
