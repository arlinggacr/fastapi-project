"""Registration, login, token refresh and password change."""

from __future__ import annotations

import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.constants.enums import UserRole
from src.common.responses import ApiError, conflict, unauthorized
from src.core.config import get_settings
from src.core.redis import Gateway
from src.modules.auth.dtos.token_dto import TokenPairResponse
from src.modules.users.dtos.user_dto import (
    PasswordChangeDTO,
    UserLoginDTO,
    UserRegisterDTO,
)
from src.modules.users.entities.user import User
from src.modules.users.repositories.user_repository import UserRepository
from src.utils.rate_limit import hit
from src.utils.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)

LOGIN_LIMIT = 10
LOGIN_WINDOW_SECONDS = 60


class AuthService:
    def __init__(self, session: AsyncSession, gateway: Gateway | None = None) -> None:
        self._repo = UserRepository(session)
        self._gateway = gateway

    # -- registration --------------------------------------------------------
    async def register(self, dto: UserRegisterDTO) -> User:
        existing = await self._repo.find_by_email_or_username(dto.email, dto.username)
        if existing is not None:
            if existing.email == dto.email:
                raise conflict("EMAIL_TAKEN", "email is already registered")
            raise conflict("USERNAME_TAKEN", "username is already registered")

        user = await self._repo.create(
            email=str(dto.email),
            username=dto.username,
            hashed_password=hash_password(dto.password),
            role=UserRole.user,
        )
        await self._repo.commit()
        return await self._repo.refresh(user)

    # -- login ---------------------------------------------------------------
    async def login(self, dto: UserLoginDTO, *, client_key: str = "") -> TokenPairResponse:
        if self._gateway is not None and client_key:
            # Key on IP + email so one shared IP (NAT, CI) cannot lock
            # everybody out, while a single account is still protected.
            allowed = await hit(
                self._gateway,
                f"ratelimit:login:{client_key}:{dto.email}",
                limit=LOGIN_LIMIT,
                window_seconds=LOGIN_WINDOW_SECONDS,
            )
            if not allowed:
                raise ApiError(429, "RATE_LIMITED", "Too many login attempts, try again later")

        user = await self._repo.get_by_email(str(dto.email))
        if user is None or not verify_password(dto.password, user.hashed_password):
            raise unauthorized("Incorrect email or password")
        if not user.is_active:
            raise ApiError(403, "ACCOUNT_DISABLED", "Account is disabled")
        return self.issue_tokens(user)

    def issue_tokens(self, user: User) -> TokenPairResponse:
        return TokenPairResponse(
            access_token=create_access_token(user.id),
            refresh_token=create_refresh_token(user.id),
            expires_in=get_settings().access_token_ttl_minutes * 60,
        )

    async def refresh(self, refresh_token: str) -> TokenPairResponse:
        try:
            claims = decode_token(refresh_token, expected_type="refresh")
        except jwt.InvalidTokenError as exc:
            raise unauthorized("Invalid refresh token") from exc

        try:
            from uuid import UUID

            user_id = UUID(claims["sub"])
        except (KeyError, ValueError, TypeError) as exc:
            raise unauthorized("Invalid refresh token") from exc

        user = await self._repo.get_by_id(user_id)
        if user is None or not user.is_active:
            raise unauthorized("Invalid refresh token")
        return self.issue_tokens(user)

    # -- password ------------------------------------------------------------
    async def change_password(self, user: User, dto: PasswordChangeDTO) -> None:
        if not verify_password(dto.current_password, user.hashed_password):
            raise ApiError(400, "BAD_PASSWORD", "Current password is incorrect")
        await self._repo.set_password(user, hash_password(dto.new_password))
        await self._repo.commit()
