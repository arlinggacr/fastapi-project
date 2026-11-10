"""Bid use-case: place a bid, emit events, warn the outbid user."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.common.constants.enums import NotificationType
from src.common.responses import ApiError, conflict, not_found
from src.core.keys import events_key
from src.core.realtime import Broker
from src.core.redis import Gateway
from src.modules.auctions.dtos.bid_response import BidAcceptedResponse, BidResponse
from src.modules.auctions.repositories.auction_repository import AuctionRepository
from src.modules.auctions.repositories.bid_repository import BidRepository
from src.modules.auctions.services.bidding_service import BiddingService, BidError
from src.modules.notifications.services.notification_service import NotificationService
from src.modules.users.entities.user import User

_STATUS_BY_CODE = {
    "AUCTION_NOT_LIVE": 409,
    "AUCTION_NOT_ACTIVE": 409,
    "AUCTION_ENDED": 409,
    "SELLER_CANNOT_BID": 409,
    "BID_TOO_LOW": 409,
}


class BidService:
    def __init__(self, session: AsyncSession, gateway: Gateway, broker: Broker) -> None:
        self._session = session
        self._broker = broker
        self._auctions = AuctionRepository(session)
        self._bids = BidRepository(session)
        self._bidding = BiddingService(session, gateway)
        self._notifications = NotificationService(session, broker)

    async def place(
        self, *, auction_id: UUID, bidder: User, amount: Decimal
    ) -> BidAcceptedResponse:
        auction = await self._auctions.get_by_id(auction_id)
        if auction is None:
            raise not_found("Auction")

        try:
            result = await self._bidding.place_bid(auction=auction, bidder=bidder, amount=amount)
        except BidError as exc:
            raise ApiError(
                _STATUS_BY_CODE.get(exc.code, 409), exc.code, exc.message, **exc.extra
            ) from exc

        # Warn whoever was leading before this bid.
        if result.previous_leader_id and result.previous_leader_id != bidder.id:
            await self._notifications.notify(
                user_id=result.previous_leader_id,
                type_=NotificationType.outbid.value,
                payload={
                    "auction_id": str(auction.id),
                    "title": auction.title,
                    "new_price": str(result.amount),
                    "by": bidder.username,
                },
                auction_id=auction.id,
            )
            await self._session.commit()

        await self._broker.publish(
            events_key(auction.id),
            {
                "type": NotificationType.bid_placed.value,
                "auction_id": str(auction.id),
                "data": {
                    "bid_id": str(result.bid.id),
                    "amount": str(result.amount),
                    "bidder_id": str(bidder.id),
                    "bidder_username": bidder.username,
                    "current_price": str(result.amount),
                    "min_next_bid": str(result.min_next_bid),
                    "end_time": result.end_time.isoformat(),
                    "bid_count": result.bid_count,
                    "extended": result.extended,
                },
            },
        )

        return BidAcceptedResponse(
            bid=BidResponse.model_validate(result.bid),
            current_price=result.amount,
            min_next_bid=result.min_next_bid,
            end_time=result.end_time,
            extended=result.extended,
            bid_count=result.bid_count,
        )

    async def history(self, auction_id: UUID, *, limit: int = 50) -> list[BidResponse]:
        rows = await self._bids.list_for_auction(auction_id, limit=limit)
        return [BidResponse.model_validate(row) for row in rows]


__all__ = ["BidService", "conflict"]
