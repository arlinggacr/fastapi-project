"""Notification fan-out: persist + push on the user's realtime stream."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.keys import user_events_key
from src.core.realtime import Broker
from src.modules.notifications.repositories.notification_repository import (
    NotificationRepository,
)


class NotificationService:
    def __init__(self, session: AsyncSession, broker: Broker) -> None:
        self._repo = NotificationRepository(session)
        self._broker = broker

    async def notify(
        self,
        *,
        user_id: UUID,
        type_: str,
        payload: dict[str, Any],
        auction_id: UUID | None = None,
        commit: bool = False,
    ) -> None:
        await self._repo.create(
            user_id=user_id, type_=type_, payload=payload, auction_id=auction_id
        )
        await self._broker.publish(
            user_events_key(user_id),
            {
                "type": type_,
                "user_id": str(user_id),
                "auction_id": str(auction_id) if auction_id else None,
                "data": payload,
            },
        )
        if commit:
            await self._repo.commit()
