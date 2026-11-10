"""Persistence for users.

All statements are built with SQLAlchemy expressions, which are compiled to
bound parameters - no value is ever interpolated into SQL text.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.constants.enums import UserRole
from src.modules.users.entities.user import User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # -- reads ---------------------------------------------------------------
    async def get_by_id(self, user_id: UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_username(self, username: str) -> User | None:
        stmt = select(User).where(User.username == username)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def find_by_email_or_username(self, email: str, username: str) -> User | None:
        stmt = select(User).where(or_(User.email == email, User.username == username))
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_paginated(self, *, offset: int, limit: int) -> list[User]:
        stmt = (
            select(User)
            .order_by(User.created_at.desc())
            .offset(max(offset, 0))
            .limit(max(min(limit, 200), 1))
        )
        return list((await self._session.execute(stmt)).scalars())

    async def count(self) -> int:
        return (await self._session.execute(select(func.count(User.id)))).scalar_one()

    # -- writes --------------------------------------------------------------
    async def create(
        self,
        *,
        email: str,
        username: str,
        hashed_password: str,
        role: UserRole = UserRole.user,
    ) -> User:
        user = User(
            email=email,
            username=username,
            hashed_password=hashed_password,
            role=role,
        )
        self._session.add(user)
        await self._session.flush()
        return user

    async def set_role(self, user: User, role: UserRole) -> User:
        user.role = role
        await self._session.flush()
        return user

    async def set_active(self, user: User, is_active: bool) -> User:
        user.is_active = is_active
        await self._session.flush()
        return user

    async def set_password(self, user: User, hashed_password: str) -> User:
        user.hashed_password = hashed_password
        await self._session.flush()
        return user

    # -- transaction control -------------------------------------------------
    async def commit(self) -> None:
        await self._session.commit()

    async def refresh(self, user: User) -> User:
        await self._session.refresh(user)
        return user
