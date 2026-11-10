"""WebSocket route for a single auction's live feed.

``/ws/auctions/{id}?token=<access_token>``

Anonymous clients may spectate read-only; a valid token adds identity and
lets the UI know whether the viewer is the seller.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from uuid import UUID

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.keys import events_key
from src.core.realtime import Broker
from src.core.redis import Gateway
from src.core.time import now_ms
from src.database.session import SessionLocal
from src.modules.auctions.repositories.auction_repository import AuctionRepository
from src.modules.auctions.repositories.bid_repository import BidRepository
from src.modules.auctions.services.bidding_service import BiddingService, next_min_bid
from src.utils.deps import get_user_from_token

logger = logging.getLogger(__name__)
router = APIRouter(tags=["websockets"])

HEARTBEAT_SECONDS = 25


async def _authenticate(websocket: WebSocket, token: str | None):
    if not token:
        return None
    async with SessionLocal() as session:
        try:
            return await get_user_from_token(token, session)
        except Exception:
            return None


async def _keepalive(websocket: WebSocket, stop: asyncio.Event) -> None:
    while not stop.is_set():
        await asyncio.sleep(HEARTBEAT_SECONDS)
        if stop.is_set():
            return
        with contextlib.suppress(Exception):
            await websocket.send_json({"type": "ping", "ts": now_ms()})


async def _snapshot(session: AsyncSession, gateway: Gateway, auction_id: UUID, user):
    auction = await AuctionRepository(session).get_by_id(auction_id)
    if auction is None:
        return None

    bids = BidRepository(session)
    count = await bids.count_for_auction(auction.id)
    state = await BiddingService(session, gateway).read_state(auction.id)
    current_price = auction.current_price
    if state and state.get("current_price_cents"):
        from src.core.money import from_cents

        current_price = from_cents(int(state["current_price_cents"]))
    if state and state.get("bid_count") is not None:
        count = int(state["bid_count"])

    return {
        "type": "snapshot",
        "auction_id": str(auction.id),
        "data": {
            "title": auction.title,
            "status": auction.status.value,
            "current_price": str(current_price),
            "min_next_bid": str(next_min_bid(current_price, auction.min_increment, count)),
            "end_time": auction.end_time.isoformat(),
            "bid_count": count,
            "seller_id": str(auction.seller_id),
            "seller_username": auction.seller.username,
            "you": (
                {
                    "id": str(user.id),
                    "username": user.username,
                    "is_seller": user.id == auction.seller_id,
                }
                if user
                else None
            ),
        },
    }


@router.websocket("/ws/auctions/{auction_id}")
async def auction_socket(
    websocket: WebSocket,
    auction_id: UUID,
    token: str | None = Query(default=None),
) -> None:
    gateway: Gateway = websocket.app.state.gateway
    broker: Broker = websocket.app.state.broker

    user = await _authenticate(websocket, token)
    await websocket.accept()

    async with SessionLocal() as session:
        snapshot = await _snapshot(session, gateway, auction_id, user)
    if snapshot is None:
        await websocket.close(code=4404, reason="Auction not found")
        return

    await websocket.send_json(snapshot)

    stop = asyncio.Event()
    heartbeat = asyncio.create_task(_keepalive(websocket, stop))
    last_id = await gateway.xlast_id(events_key(auction_id))

    try:
        async for event in broker.listen(events_key(auction_id), last_id=last_id):
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("auction socket failed for %s", auction_id)
    finally:
        stop.set()
        heartbeat.cancel()
        with contextlib.suppress(Exception):
            await heartbeat
