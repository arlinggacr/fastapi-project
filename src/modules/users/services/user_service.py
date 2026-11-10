"""User profile and administrative user management."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.common.constants.enums import UserRole
from src.common.helpers.pagination import build_page
from src.common.responses import conflict, forbidden, not_found
from src.modules.users.entities.user import User
from src.modules.users.repositories.user_repository import UserRepository


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = UserRepository(session)

    async def get(self, user_id: UUID) -> User:
        user = await self._repo.get_by_id(user_id)
        if user is None:
            raise not_found("User")
        return user

    async def list(self, *, page: int, page_size: int) -> list[User]:
        pager = build_page(page, page_size)
        return await self._repo.list_paginated(offset=pager.offset, limit=pager.limit)

    async def count(self) -> int:
        return await self._repo.count()

    async def set_role(self, *, actor: User, user_id: UUID, role: UserRole) -> User:
        if actor.id == user_id:
            raise conflict("SELF_EDIT", "You cannot change your own role")
        target = await self._repo.get_by_id(user_id)
        if target is None:
            raise not_found("User")
        await self._repo.set_role(target, role)
        await self._repo.commit()
        return await self._repo.refresh(target)

    async def set_active(self, *, actor: User, user_id: UUID, is_active: bool) -> User:
        if actor.id == user_id:
            raise conflict("SELF_EDIT", "You cannot disable your own account")
        target = await self._repo.get_by_id(user_id)
        if target is None:
            raise not_found("User")
        if not is_active and target.is_admin:
            raise forbidden("Refusing to disable an administrator account")
        await self._repo.set_active(target, is_active)
        await self._repo.commit()
        return await self._repo.refresh(target)
