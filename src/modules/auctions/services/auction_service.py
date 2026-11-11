"""Auction use-cases: create, read, edit, cancel, watch."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.common.constants.enums import AuctionStatus
from src.common.helpers.pagination import build_page
from src.common.responses import ApiError, forbidden, not_found
from src.core.realtime import Broker
from src.core.redis import Gateway
from src.core.storage import S3Storage
from src.core.time import utcnow
from src.modules.auctions.dtos.auction_dto import (
    AuctionCreateDTO,
    AuctionQueryDTO,
    AuctionUpdateDTO,
)
from src.modules.auctions.dtos.auction_response import AuctionPageResponse, AuctionResponse
from src.modules.auctions.entities.auction import Auction
from src.modules.auctions.repositories.auction_repository import AuctionRepository
from src.modules.auctions.repositories.bid_repository import BidRepository
from src.modules.auctions.services.bidding_service import BiddingService, next_min_bid
from src.modules.auctions.services.image_service import AuctionImageService
from src.modules.auctions.services.lifecycle_service import AuctionLifecycleService
from src.modules.auctions.services.watcher_service import WatcherService
from src.modules.users.dtos.user_response import PublicUserResponse
from src.modules.users.entities.user import User

# Tolerate small clock skew when a seller submits an "already started" auction.
CLOCK_SKEW_SECONDS = 300


class AuctionService:
    def __init__(
        self,
        session: AsyncSession,
        gateway: Gateway,
        broker: Broker,
        storage: S3Storage | None = None,
    ) -> None:
        self._session = session
        self._gateway = gateway
        self._broker = broker
        self._storage = storage
        self._auctions = AuctionRepository(session)
        self._bids = BidRepository(session)
        self._bidding = BiddingService(session, gateway)
        self._watchers = WatcherService(gateway)
        self._lifecycle = AuctionLifecycleService(session, gateway, broker)

    # -- create --------------------------------------------------------------
    async def create(self, seller: User, dto: AuctionCreateDTO) -> AuctionResponse:
        now = utcnow()
        start = _as_utc(dto.start_time)
        end = _as_utc(dto.end_time)

        if end <= now:
            raise ApiError(422, "END_IN_PAST", "end_time must be in the future")
        if start < now and (now - start).total_seconds() > CLOCK_SKEW_SECONDS:
            raise ApiError(422, "START_IN_PAST", "start_time cannot be in the past")

        auction = await self._auctions.create(
            seller_id=seller.id,
            title=dto.title,
            description=dto.description,
            category=dto.category,
            image_url=dto.image_url,
            starting_price=dto.starting_price,
            min_increment=dto.min_increment,
            start_time=start,
            end_time=end,
        )
        await self._auctions.commit()

        auction = await self._auctions.get_by_id(auction.id)
        if auction is None:  # pragma: no cover - defensive
            raise not_found("Auction")

        if start <= now:
            await self._lifecycle.activate(auction)

        return await self.to_response(auction, viewer=seller)

    # -- read ----------------------------------------------------------------
    async def get(self, auction_id: UUID, viewer: User | None = None) -> AuctionResponse:
        auction = await self._auctions.get_by_id(auction_id)
        if auction is None:
            raise not_found("Auction")
        return await self.to_response(auction, viewer=viewer)

    async def list(
        self,
        *,
        query: AuctionQueryDTO,
        viewer: User | None,
        page: int,
        page_size: int,
        seller_id: UUID | None = None,
    ) -> AuctionPageResponse:
        pager = build_page(page, page_size)
        rows = await self._auctions.list_paginated(
            offset=pager.offset,
            limit=pager.limit,
            status=query.status,
            category=query.category,
            seller_id=seller_id,
            search=query.q,
        )
        total = await self._auctions.count(
            status=query.status,
            category=query.category,
            seller_id=seller_id,
            search=query.q,
        )
        counts = await self._bids.counts_for_auctions([row.id for row in rows])

        items = [
            await self.to_response(row, viewer=viewer, bid_count=counts.get(row.id, 0))
            for row in rows
        ]
        return AuctionPageResponse(
            items=items, total=total, page=pager.page, page_size=pager.page_size
        )

    # -- edit ----------------------------------------------------------------
    async def update(self, auction_id: UUID, user: User, dto: AuctionUpdateDTO) -> AuctionResponse:
        auction = await self._auctions.get_by_id(auction_id)
        if auction is None:
            raise not_found("Auction")
        self._assert_can_manage(auction, user)
        if auction.status != AuctionStatus.scheduled:
            raise ApiError(409, "NOT_EDITABLE", "Only scheduled auctions can be edited")

        values = dto.model_dump(exclude_unset=True)
        start = _as_utc(values.get("start_time", auction.start_time))
        end = _as_utc(values.get("end_time", auction.end_time))
        if end <= start:
            raise ApiError(422, "BAD_WINDOW", "end_time must be after start_time")

        await self._auctions.apply_updates(auction, values)
        await self._auctions.commit()
        refreshed = await self._auctions.get_by_id(auction_id)
        if refreshed is None:  # pragma: no cover - defensive
            raise not_found("Auction")
        return await self.to_response(refreshed, viewer=user)

    async def cancel(self, auction_id: UUID, user: User) -> AuctionResponse:
        auction = await self._auctions.get_by_id(auction_id)
        if auction is None:
            raise not_found("Auction")
        self._assert_can_manage(auction, user)
        if auction.status == AuctionStatus.ended:
            raise ApiError(409, "ALREADY_ENDED", "Auction already ended")

        await self._auctions.set_status(auction, AuctionStatus.cancelled)
        await self._bidding.seed_state(auction, status=AuctionStatus.cancelled.value)
        await self._auctions.commit()
        return await self.to_response(auction, viewer=user)

    async def delete(self, auction_id: UUID, user: User) -> None:
        auction = await self._auctions.get_by_id(auction_id)
        if auction is None:
            raise not_found("Auction")
        self._assert_can_manage(auction, user)
        if auction.status == AuctionStatus.active:
            raise ApiError(409, "IS_ACTIVE", "Cancel the auction before deleting it")

        # The rows cascade away with the auction, but the objects in the bucket
        # do not, so the image service clears those first.
        if self._storage is not None:
            await AuctionImageService(self._session, self._storage).purge_objects(auction.id)

        await self._auctions.delete(auction)
        await self._auctions.commit()

    # -- watch ---------------------------------------------------------------
    async def watch(self, auction_id: UUID, user: User) -> None:
        if await self._auctions.get_by_id(auction_id) is None:
            raise not_found("Auction")
        await self._watchers.add(auction_id, user.id)

    async def unwatch(self, auction_id: UUID, user: User) -> None:
        await self._watchers.remove(auction_id, user.id)

    # -- mapping -------------------------------------------------------------
    async def to_response(
        self,
        auction: Auction,
        *,
        viewer: User | None = None,
        bid_count: int | None = None,
    ) -> AuctionResponse:
        if bid_count is None:
            bid_count = await self._bids.count_for_auction(auction.id)

        watching = await self._watchers.contains(auction.id, viewer.id) if viewer else False
        return AuctionResponse(
            id=auction.id,
            title=auction.title,
            description=auction.description,
            category=auction.category,
            image_url=auction.image_url,
            starting_price=auction.starting_price,
            min_increment=auction.min_increment,
            current_price=auction.current_price,
            min_next_bid=next_min_bid(auction.current_price, auction.min_increment, bid_count),
            current_winner_id=auction.current_winner_id,
            status=auction.status,
            start_time=auction.start_time,
            end_time=auction.end_time,
            extended_count=auction.extended_count,
            seller=PublicUserResponse.model_validate(auction.seller),
            bid_count=bid_count,
            watchers=await self._watchers.count(auction.id),
            is_seller=viewer is not None and viewer.id == auction.seller_id,
            is_watching=watching,
            created_at=auction.created_at,
        )

    @staticmethod
    def _assert_can_manage(auction: Auction, user: User) -> None:
        if auction.seller_id != user.id and not user.is_admin:
            raise forbidden("Only the seller or an admin can manage this auction")


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)
