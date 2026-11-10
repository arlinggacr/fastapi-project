"""Auth routes: /auth/*"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.redis import Gateway
from src.database.session import get_session
from src.modules.auth.dtos.token_dto import RefreshRequestDTO, TokenPairResponse
from src.modules.auth.services.auth_service import AuthService
from src.modules.users.dtos.user_dto import (
    PasswordChangeDTO,
    UserLoginDTO,
    UserRegisterDTO,
)
from src.modules.users.dtos.user_response import UserResponse
from src.modules.users.entities.user import User
from src.utils.deps import get_current_user, get_gateway

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    payload: UserRegisterDTO,
    session: AsyncSession = Depends(get_session),
) -> User:
    return await AuthService(session).register(payload)


@router.post("/login", response_model=TokenPairResponse)
async def login(
    payload: UserLoginDTO,
    request: Request,
    session: AsyncSession = Depends(get_session),
    gateway: Gateway = Depends(get_gateway),
) -> TokenPairResponse:
    client_key = request.client.host if request.client else "unknown"
    return await AuthService(session, gateway).login(payload, client_key=client_key)


@router.post("/refresh", response_model=TokenPairResponse)
async def refresh(
    payload: RefreshRequestDTO,
    session: AsyncSession = Depends(get_session),
) -> TokenPairResponse:
    return await AuthService(session).refresh(payload.refresh_token)


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    payload: PasswordChangeDTO,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    await AuthService(session).change_password(user, payload)
