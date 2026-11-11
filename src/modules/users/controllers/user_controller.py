"""User routes: /users/*"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.session import get_session
from src.modules.users.dtos.user_response import PublicUserResponse, UserResponse
from src.modules.users.entities.user import User
from src.modules.users.services.user_service import UserService
from src.utils.deps import get_current_user
from src.utils.responses import SuccessEnvelope, success

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=SuccessEnvelope[UserResponse])
async def read_me(user: User = Depends(get_current_user)) -> dict[str, Any]:
    return success(user, "Profile retrieved")


@router.get("/{user_id}", response_model=SuccessEnvelope[PublicUserResponse])
async def read_user(
    user_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user = await UserService(session).get(user_id)
    return success(user, "User retrieved")
