"""Persistence for notifications."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.notifications.entities.notification import Notification


class NotificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        user_id: UUID,
        type_: str,
        payload: dict,
        auction_id: UUID | None = None,
    ) -> Notification:
        notification = Notification(
            user_id=user_id,
            auction_id=auction_id,
            type=type_,
            payload=payload,
        )
        self._session.add(notification)
        await self._session.flush()
        return notification

    async def get_by_id(self, notification_id: UUID) -> Notification | None:
        return await self._session.get(Notification, notification_id)

    async def list_for_user(
        self, user_id: UUID, *, unread_only: bool = False, limit: int = 50
    ) -> list[Notification]:
        stmt = select(Notification).where(Notification.user_id == user_id)
        if unread_only:
            stmt = stmt.where(Notification.is_read.is_(False))
        stmt = stmt.order_by(Notification.created_at.desc()).limit(max(min(limit, 200), 1))
        return list((await self._session.execute(stmt)).scalars())

    async def count_unread(self, user_id: UUID) -> int:
        stmt = select(func.count(Notification.id)).where(
            Notification.user_id == user_id, Notification.is_read.is_(False)
        )
        return (await self._session.execute(stmt)).scalar_one()

    async def mark_read(self, notification: Notification) -> Notification:
        notification.is_read = True
        await self._session.flush()
        return notification

    async def commit(self) -> None:
        await self._session.commit()
