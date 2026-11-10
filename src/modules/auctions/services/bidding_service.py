"""Atomic bidding.

The price check and the state mutation happen inside one Lua script, so two
concurrent bids can never both win the same price point. Redis is the
arbiter of "who bid first"; Postgres stores the durable ledger.

State hash layout (``auction:{id}:state``):

    status              active | scheduled | ended | cancelled
    seller_id           uuid
    current_price_cents int
    min_increment_cents int
    end_time_ms         int
    top_bidder_id       uuid
    top_bidder_name     string
    bid_count           int
    extended_count      int
    version             int (bumped per accepted bid)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.common.constants.enums import AuctionStatus
from src.core.config import get_settings
from src.core.keys import state_key
from src.core.money import from_cents, to_cents
from src.core.redis import Gateway
from src.core.time import from_ms, now_ms
from src.modules.auctions.entities.auction import Auction
from src.modules.auctions.entities.bid import Bid
from src.modules.auctions.repositories.auction_repository import AuctionRepository
from src.modules.auctions.repositories.bid_repository import BidRepository
from src.modules.users.entities.user import User

logger = logging.getLogger(__name__)

BID_SCRIPT = """
local key = KEYS[1]
local bidder_id = ARGV[1]
local bidder_name = ARGV[2]
local amount = tonumber(ARGV[3])
local now = tonumber(ARGV[4])
local extension_window = tonumber(ARGV[5])
local extension_ms = tonumber(ARGV[6])

if redis.call('EXISTS', key) == 0 then
  return {0, 'AUCTION_NOT_LIVE', '0', '0', '0', '0'}
end

local state = redis.call('HMGET', key,
  'status', 'seller_id', 'current_price_cents', 'min_increment_cents',
  'end_time_ms', 'bid_count', 'extended_count')

local status = state[1]
if status ~= 'active' then
  return {0, 'AUCTION_NOT_ACTIVE', '0', '0', '0', '0'}
end
if state[2] == bidder_id then
  return {0, 'SELLER_CANNOT_BID', '0', '0', '0', '0'}
end

local end_time = tonumber(state[5])
if now >= end_time then
  return {0, 'AUCTION_ENDED', '0', '0', '0', '0'}
end

local current = tonumber(state[3])
local increment = tonumber(state[4])
local bid_count = tonumber(state[6]) or 0

-- With no bids yet the starting price is the minimum; afterwards the
-- increment applies on top of the current price.
local min_required = current
if bid_count > 0 then
  min_required = current + increment
end

if amount < min_required then
  return {0, 'BID_TOO_LOW', tostring(min_required), tostring(end_time), '0', '0'}
end

local extended = 0
local extended_count = tonumber(state[7]) or 0
if (end_time - now) <= extension_window then
  end_time = end_time + extension_ms
  extended = 1
  extended_count = extended_count + 1
end

bid_count = bid_count + 1

redis.call('HSET', key,
  'current_price_cents', amount,
  'top_bidder_id', bidder_id,
  'top_bidder_name', bidder_name,
  'end_time_ms', end_time,
  'bid_count', bid_count,
  'extended_count', extended_count)
redis.call('HINCRBY', key, 'version', 1)

return {1, 'OK', tostring(amount), tostring(end_time), tostring(bid_count), tostring(extended)}
"""

_ERROR_MESSAGES = {
    "AUCTION_NOT_LIVE": "Auction is not live yet",
    "AUCTION_NOT_ACTIVE": "Auction is not accepting bids",
    "SELLER_CANNOT_BID": "You cannot bid on your own auction",
    "AUCTION_ENDED": "Auction has already ended",
    "BID_TOO_LOW": "Bid is below the minimum required amount",
}


class BidError(Exception):
    """A rejected bid. ``code`` is stable and machine readable."""

    def __init__(self, code: str, message: str | None = None, **extra: str) -> None:
        super().__init__(message or _ERROR_MESSAGES.get(code, "Bid rejected"))
        self.code = code
        self.message = message or _ERROR_MESSAGES.get(code, "Bid rejected")
        self.extra = extra


@dataclass(slots=True)
class BidResult:
    bid: Bid
    amount: Decimal
    end_time: datetime
    bid_count: int
    extended: bool
    min_next_bid: Decimal
    previous_leader_id: UUID | None


def next_min_bid(current: Decimal, increment: Decimal, bid_count: int) -> Decimal:
    """Lowest amount a new bid may have."""
    return current if bid_count == 0 else current + increment


class BiddingService:
    def __init__(self, session: AsyncSession, gateway: Gateway) -> None:
        self._session = session
        self._gateway = gateway
        self._auctions = AuctionRepository(session)
        self._bids = BidRepository(session)

    # -- state ---------------------------------------------------------------
    async def seed_state(self, auction: Auction, *, status: str | None = None) -> None:
        await self._gateway.hset(
            state_key(auction.id),
            {
                "status": status or auction.status.value,
                "seller_id": str(auction.seller_id),
                "current_price_cents": to_cents(auction.current_price),
                "min_increment_cents": to_cents(auction.min_increment),
                "end_time_ms": int(auction.end_time.timestamp() * 1000),
                "top_bidder_id": str(auction.current_winner_id or ""),
                "top_bidder_name": "",
                "bid_count": 0,
                "extended_count": auction.extended_count,
                "version": "0",
            },
        )

    async def read_state(self, auction_id: UUID) -> dict[str, str]:
        return await self._gateway.hgetall(state_key(auction_id))

    async def ensure_state(self, auction: Auction) -> dict[str, str]:
        """Return live state, rehydrating from Postgres on a cold cache."""
        state = await self.read_state(auction.id)
        if state:
            return state
        if auction.status != AuctionStatus.active:
            raise BidError("AUCTION_NOT_ACTIVE")
        await self.sync_from_db(auction)
        return await self.read_state(auction.id)

    async def sync_from_db(self, auction: Auction) -> None:
        total = await self._bids.count_for_auction(auction.id)
        await self.seed_state(auction)
        await self._gateway.hset(
            state_key(auction.id),
            {
                "bid_count": total,
                "top_bidder_id": str(auction.current_winner_id or ""),
            },
        )

    # -- bidding -------------------------------------------------------------
    async def place_bid(self, *, auction: Auction, bidder: User, amount: Decimal) -> BidResult:
        settings = get_settings()

        if auction.seller_id == bidder.id:
            raise BidError("SELLER_CANNOT_BID")

        state = await self.ensure_state(auction)
        previous_leader = _parse_uuid(state.get("top_bidder_id"))

        result = await self._gateway.eval(
            BID_SCRIPT,
            [state_key(auction.id)],
            [
                str(bidder.id),
                bidder.username,
                to_cents(amount),
                now_ms(),
                settings.extension_window_seconds * 1000,
                settings.extension_seconds * 1000,
            ],
        )

        if not int(result[0]):
            code = str(result[1])
            extra: dict[str, str] = {}
            if code == "BID_TOO_LOW":
                extra["min_next_bid"] = str(from_cents(int(result[2])))
            raise BidError(code, **extra)

        amount_cents = int(result[2])
        end_time = from_ms(int(result[3]))
        bid_count = int(result[4])
        extended = bool(int(result[5]))
        accepted_amount = from_cents(amount_cents)

        bid = await self._bids.create(
            auction_id=auction.id, bidder_id=bidder.id, amount=accepted_amount
        )

        auction.current_price = accepted_amount
        auction.current_winner_id = bidder.id
        auction.end_time = end_time
        if extended:
            auction.extended_count += 1

        await self._auctions.commit()
        await self._bids.refresh(bid)

        return BidResult(
            bid=bid,
            amount=accepted_amount,
            end_time=end_time,
            bid_count=bid_count,
            extended=extended,
            min_next_bid=next_min_bid(accepted_amount, auction.min_increment, bid_count),
            previous_leader_id=previous_leader,
        )


def _parse_uuid(value: str | None) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(value)
    except (ValueError, TypeError):
        return None
