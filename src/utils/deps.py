"""Shared FastAPI dependencies."""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.responses import forbidden, unauthorized
from src.core.realtime import Broker
from src.core.redis import Gateway
from src.database.session import get_session
from src.modules.users.entities.user import User
from src.modules.users.repositories.user_repository import UserRepository
from src.utils.security import decode_token

bearer_scheme = HTTPBearer(auto_error=False)


def get_gateway(request: Request) -> Gateway:
    gateway = getattr(request.app.state, "gateway", None)
    if gateway is None:
        raise unauthorized("Realtime backend is unavailable")
    return gateway


def get_broker(request: Request) -> Broker:
    broker = getattr(request.app.state, "broker", None)
    if broker is None:
        raise unauthorized("Realtime backend is unavailable")
    return broker


async def get_user_from_token(token: str, session: AsyncSession) -> User:
    """Resolve a bearer token to a live, active user."""
    try:
        payload = decode_token(token, expected_type="access")
    except jwt.InvalidTokenError as exc:
        raise unauthorized() from exc

    try:
        user_id = UUID(payload["sub"])
    except (KeyError, ValueError, TypeError) as exc:
        raise unauthorized() from exc

    user = await UserRepository(session).get_by_id(user_id)
    if user is None or not user.is_active:
        raise unauthorized()
    return user


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_session),
) -> User:
    if credentials is None or not credentials.credentials:
        raise unauthorized()
    return await get_user_from_token(credentials.credentials, session)


async def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_session),
) -> User | None:
    if credentials is None or not credentials.credentials:
        return None
    try:
        return await get_user_from_token(credentials.credentials, session)
    except Exception:
        return None


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise forbidden("Admin privileges required")
    return user


async def db_session() -> AsyncIterator[AsyncSession]:
    """Alias kept for readability in controllers."""
    async for session in get_session():
        yield session


__all__ = [
    "db_session",
    "get_broker",
    "get_current_user",
    "get_gateway",
    "get_optional_user",
    "get_session",
    "get_user_from_token",
    "require_admin",
]
