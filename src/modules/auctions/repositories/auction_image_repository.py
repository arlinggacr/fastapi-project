"""Persistence for auction images."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.auctions.entities.auction_image import AuctionImage


class AuctionImageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # -- reads ---------------------------------------------------------------
    async def get_by_id(self, image_id: UUID) -> AuctionImage | None:
        return await self._session.get(AuctionImage, image_id)

    async def list_for_auction(self, auction_id: UUID) -> list[AuctionImage]:
        stmt = (
            select(AuctionImage)
            .where(AuctionImage.auction_id == auction_id)
            .order_by(AuctionImage.position.asc(), AuctionImage.created_at.asc())
        )
        return list((await self._session.execute(stmt)).scalars())

    async def count_for_auction(self, auction_id: UUID) -> int:
        stmt = select(func.count()).select_from(AuctionImage).where(
            AuctionImage.auction_id == auction_id
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def list_keys(self, auction_id: UUID) -> list[str]:
        """Object keys for an auction's images, for bucket cleanup."""
        stmt = select(AuctionImage.key).where(AuctionImage.auction_id == auction_id)
        return list((await self._session.execute(stmt)).scalars())

    async def next_position(self, auction_id: UUID) -> int:
        stmt = select(func.max(AuctionImage.position)).where(
            AuctionImage.auction_id == auction_id
        )
        current = (await self._session.execute(stmt)).scalar_one_or_none()
        return 0 if current is None else int(current) + 1

    # -- writes --------------------------------------------------------------
    async def create(
        self,
        *,
        auction_id: UUID,
        key: str,
        url: str,
        content_type: str,
        size_bytes: int,
        position: int,
    ) -> AuctionImage:
        image = AuctionImage(
            auction_id=auction_id,
            key=key,
            url=url,
            content_type=content_type,
            size_bytes=size_bytes,
            position=position,
        )
        self._session.add(image)
        await self._session.flush()
        return image

    async def delete(self, image: AuctionImage) -> None:
        await self._session.delete(image)
        await self._session.flush()

    async def commit(self) -> None:
        await self._session.commit()
