"""Who is watching an auction (Redis sets, keyed per auction)."""

from __future__ import annotations

from uuid import UUID

from src.core.config import get_settings
from src.core.redis import Gateway


def _key(auction_id: UUID | str) -> str:
    return f"{get_settings().key_prefix}:auction:{auction_id}:watchers"


class WatcherService:
    def __init__(self, gateway: Gateway) -> None:
        self._gateway = gateway

    async def add(self, auction_id: UUID, user_id: UUID) -> int:
        return await self._gateway.sadd(_key(auction_id), str(user_id))

    async def remove(self, auction_id: UUID, user_id: UUID) -> int:
        return await self._gateway.srem(_key(auction_id), str(user_id))

    async def contains(self, auction_id: UUID, user_id: UUID) -> bool:
        return await self._gateway.sismember(_key(auction_id), str(user_id))

    async def count(self, auction_id: UUID) -> int:
        return await self._gateway.scard(_key(auction_id))

    async def members(self, auction_id: UUID) -> list[UUID]:
        raw = await self._gateway.smembers(_key(auction_id))
        members: list[UUID] = []
        for value in raw:
            try:
                members.append(UUID(value))
            except (ValueError, TypeError):
                continue
        return members
