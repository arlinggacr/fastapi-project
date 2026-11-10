"""Persistence for auctions."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.common.constants.enums import AuctionStatus
from src.modules.auctions.entities.auction import Auction
from src.utils.sanitize import escape_like


class AuctionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # -- reads ---------------------------------------------------------------
    async def get_by_id(self, auction_id: UUID) -> Auction | None:
        stmt = select(Auction).options(selectinload(Auction.seller)).where(Auction.id == auction_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_for_update(self, auction_id: UUID) -> Auction | None:
        """Row lock, used when mutating a live auction."""
        stmt = (
            select(Auction)
            .options(selectinload(Auction.seller))
            .where(Auction.id == auction_id)
            .with_for_update()
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_paginated(
        self,
        *,
        offset: int,
        limit: int,
        status: AuctionStatus | None = None,
        category: str | None = None,
        seller_id: UUID | None = None,
        search: str | None = None,
    ) -> list[Auction]:
        stmt = select(Auction).options(selectinload(Auction.seller))
        stmt = self._apply_filters(stmt, status, category, seller_id, search)
        stmt = (
            stmt.order_by(Auction.end_time.asc())
            .offset(max(offset, 0))
            .limit(max(min(limit, 100), 1))
        )
        return list((await self._session.execute(stmt)).scalars())

    async def count(
        self,
        *,
        status: AuctionStatus | None = None,
        category: str | None = None,
        seller_id: UUID | None = None,
        search: str | None = None,
    ) -> int:
        stmt = select(func.count(Auction.id))
        stmt = self._apply_filters(stmt, status, category, seller_id, search)
        return (await self._session.execute(stmt)).scalar_one()

    async def count_all(self) -> int:
        return (await self._session.execute(select(func.count(Auction.id)))).scalar_one()

    async def count_by_status(self, status: AuctionStatus) -> int:
        stmt = select(func.count(Auction.id)).where(Auction.status == status)
        return (await self._session.execute(stmt)).scalar_one()

    async def due_to_start(self, now: datetime, limit: int = 100) -> list[Auction]:
        stmt = (
            select(Auction)
            .options(selectinload(Auction.seller))
            .where(Auction.status == AuctionStatus.scheduled, Auction.start_time <= now)
            .limit(min(limit, 500))
        )
        return list((await self._session.execute(stmt)).scalars())

    async def due_to_end(self, now: datetime, limit: int = 100) -> list[Auction]:
        stmt = (
            select(Auction)
            .options(selectinload(Auction.seller))
            .where(Auction.status == AuctionStatus.active, Auction.end_time <= now)
            .limit(min(limit, 500))
        )
        return list((await self._session.execute(stmt)).scalars())

    async def next_start_time(self) -> datetime | None:
        stmt = select(func.min(Auction.start_time)).where(Auction.status == AuctionStatus.scheduled)
        return (await self._session.execute(stmt)).scalar_one()

    async def next_end_time(self) -> datetime | None:
        stmt = select(func.min(Auction.end_time)).where(Auction.status == AuctionStatus.active)
        return (await self._session.execute(stmt)).scalar_one()

    # -- writes --------------------------------------------------------------
    async def create(
        self,
        *,
        seller_id: UUID,
        title: str,
        description: str,
        category: str,
        image_url: str | None,
        starting_price: Decimal,
        min_increment: Decimal,
        start_time: datetime,
        end_time: datetime,
    ) -> Auction:
        auction = Auction(
            seller_id=seller_id,
            title=title,
            description=description,
            category=category,
            image_url=image_url,
            starting_price=starting_price,
            min_increment=min_increment,
            current_price=starting_price,
            status=AuctionStatus.scheduled,
            start_time=start_time,
            end_time=end_time,
        )
        self._session.add(auction)
        await self._session.flush()
        return auction

    async def apply_updates(self, auction: Auction, values: dict[str, object]) -> Auction:
        allowed = {
            "title",
            "description",
            "category",
            "image_url",
            "start_time",
            "end_time",
        }
        for field, value in values.items():
            if field in allowed:
                setattr(auction, field, value)
        await self._session.flush()
        return auction

    async def set_status(self, auction: Auction, status: AuctionStatus) -> Auction:
        auction.status = status
        await self._session.flush()
        return auction

    async def delete(self, auction: Auction) -> None:
        await self._session.delete(auction)
        await self._session.flush()

    # -- helpers -------------------------------------------------------------
    @staticmethod
    def _apply_filters(stmt, status, category, seller_id, search):
        if status is not None:
            stmt = stmt.where(Auction.status == status)
        if category:
            stmt = stmt.where(Auction.category == category.lower())
        if seller_id:
            stmt = stmt.where(Auction.seller_id == seller_id)
        if search:
            # Wildcards are escaped so the term is matched literally.
            pattern = f"%{escape_like(search.lower())}%"
            stmt = stmt.where(
                or_(
                    func.lower(Auction.title).like(pattern, escape="\\"),
                    func.lower(Auction.description).like(pattern, escape="\\"),
                )
            )
        return stmt

    # -- transaction control -------------------------------------------------
    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()

    async def refresh(self, auction: Auction) -> Auction:
        await self._session.refresh(auction)
        return auction
