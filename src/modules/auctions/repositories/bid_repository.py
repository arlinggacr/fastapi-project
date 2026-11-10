"""Persistence for bids."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.modules.auctions.entities.bid import Bid


class BidRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, *, auction_id: UUID, bidder_id: UUID, amount: Decimal) -> Bid:
        bid = Bid(auction_id=auction_id, bidder_id=bidder_id, amount=amount)
        self._session.add(bid)
        await self._session.flush()
        return bid

    async def get_by_id(self, bid_id: UUID) -> Bid | None:
        stmt = select(Bid).options(selectinload(Bid.bidder)).where(Bid.id == bid_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_for_auction(self, auction_id: UUID, *, limit: int = 50) -> list[Bid]:
        stmt = (
            select(Bid)
            .options(selectinload(Bid.bidder))
            .where(Bid.auction_id == auction_id)
            .order_by(Bid.amount.desc(), Bid.created_at.asc())
            .limit(max(min(limit, 200), 1))
        )
        return list((await self._session.execute(stmt)).scalars())

    async def latest_for_user(self, auction_id: UUID, bidder_id: UUID) -> Bid | None:
        stmt = (
            select(Bid)
            .options(selectinload(Bid.bidder))
            .where(Bid.auction_id == auction_id, Bid.bidder_id == bidder_id)
            .order_by(Bid.created_at.desc())
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def count_for_auction(self, auction_id: UUID) -> int:
        stmt = select(func.count(Bid.id)).where(Bid.auction_id == auction_id)
        return (await self._session.execute(stmt)).scalar_one()

    async def counts_for_auctions(self, auction_ids: list[UUID]) -> dict[UUID, int]:
        if not auction_ids:
            return {}
        stmt = (
            select(Bid.auction_id, func.count(Bid.id))
            .where(Bid.auction_id.in_(auction_ids))
            .group_by(Bid.auction_id)
        )
        rows = (await self._session.execute(stmt)).all()
        return {auction_id: count for auction_id, count in rows}  # noqa: C416

    async def count_all(self) -> int:
        return (await self._session.execute(select(func.count(Bid.id)))).scalar_one()

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()

    async def refresh(self, bid: Bid) -> Bid:
        await self._session.refresh(bid)
        return bid
