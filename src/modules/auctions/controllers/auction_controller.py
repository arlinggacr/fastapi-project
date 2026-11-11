"""Auction routes: /auctions/*"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.realtime import Broker
from src.core.redis import Gateway
from src.database.session import get_session
from src.modules.auctions.dtos.auction_dto import (
    AuctionCreateDTO,
    AuctionQueryDTO,
    AuctionUpdateDTO,
)
from src.modules.auctions.dtos.auction_response import AuctionResponse
from src.modules.auctions.dtos.bid_dto import BidCreateDTO
from src.modules.auctions.dtos.bid_response import BidAcceptedResponse, BidResponse
from src.modules.auctions.services.auction_service import AuctionService
from src.modules.auctions.services.bid_service import BidService
from src.modules.users.entities.user import User
from src.utils.deps import (
    get_broker,
    get_current_user,
    get_gateway,
    get_optional_user,
)
from src.utils.responses import PageHandler, SuccessEnvelope, success

router = APIRouter(prefix="/auctions", tags=["auctions"])


def _service(session: AsyncSession, gateway: Gateway, broker: Broker) -> AuctionService:
    return AuctionService(session, gateway, broker)


@router.post(
    "",
    response_model=SuccessEnvelope[AuctionResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_auction(
    payload: AuctionCreateDTO,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    gateway: Gateway = Depends(get_gateway),
    broker: Broker = Depends(get_broker),
) -> dict[str, Any]:
    auction = await _service(session, gateway, broker).create(user, payload)
    return success(auction, "Auction created")


@router.get("", response_model=SuccessEnvelope[list[AuctionResponse]])
async def list_auctions(
    query: AuctionQueryDTO = Depends(),
    seller_id: UUID | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    viewer: User | None = Depends(get_optional_user),
    session: AsyncSession = Depends(get_session),
    gateway: Gateway = Depends(get_gateway),
    broker: Broker = Depends(get_broker),
) -> dict[str, Any]:
    result = await _service(session, gateway, broker).list(
        query=query, viewer=viewer, page=page, page_size=page_size, seller_id=seller_id
    )
    return success(
        result.items,
        "Auctions retrieved",
        PageHandler.build(total_data=result.total, page=result.page, page_size=page_size),
    )


@router.get("/{auction_id}", response_model=SuccessEnvelope[AuctionResponse])
async def get_auction(
    auction_id: UUID,
    viewer: User | None = Depends(get_optional_user),
    session: AsyncSession = Depends(get_session),
    gateway: Gateway = Depends(get_gateway),
    broker: Broker = Depends(get_broker),
) -> dict[str, Any]:
    auction = await _service(session, gateway, broker).get(auction_id, viewer=viewer)
    return success(auction, "Auction retrieved")


@router.patch("/{auction_id}", response_model=SuccessEnvelope[AuctionResponse])
async def update_auction(
    auction_id: UUID,
    payload: AuctionUpdateDTO,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    gateway: Gateway = Depends(get_gateway),
    broker: Broker = Depends(get_broker),
) -> dict[str, Any]:
    auction = await _service(session, gateway, broker).update(auction_id, user, payload)
    return success(auction, "Auction updated")


@router.delete("/{auction_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_auction(
    auction_id: UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    gateway: Gateway = Depends(get_gateway),
    broker: Broker = Depends(get_broker),
) -> None:
    await _service(session, gateway, broker).delete(auction_id, user)


@router.post("/{auction_id}/cancel", response_model=SuccessEnvelope[AuctionResponse])
async def cancel_auction(
    auction_id: UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    gateway: Gateway = Depends(get_gateway),
    broker: Broker = Depends(get_broker),
) -> dict[str, Any]:
    auction = await _service(session, gateway, broker).cancel(auction_id, user)
    return success(auction, "Auction cancelled")


@router.post("/{auction_id}/watch", status_code=status.HTTP_204_NO_CONTENT)
async def watch_auction(
    auction_id: UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    gateway: Gateway = Depends(get_gateway),
    broker: Broker = Depends(get_broker),
) -> None:
    await _service(session, gateway, broker).watch(auction_id, user)


@router.delete("/{auction_id}/watch", status_code=status.HTTP_204_NO_CONTENT)
async def unwatch_auction(
    auction_id: UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    gateway: Gateway = Depends(get_gateway),
    broker: Broker = Depends(get_broker),
) -> None:
    await _service(session, gateway, broker).unwatch(auction_id, user)


@router.post(
    "/{auction_id}/bids",
    response_model=SuccessEnvelope[BidAcceptedResponse],
    status_code=status.HTTP_201_CREATED,
)
async def place_bid(
    auction_id: UUID,
    payload: BidCreateDTO,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    gateway: Gateway = Depends(get_gateway),
    broker: Broker = Depends(get_broker),
) -> dict[str, Any]:
    accepted = await BidService(session, gateway, broker).place(
        auction_id=auction_id, bidder=user, amount=payload.amount
    )
    return success(accepted, "Bid accepted")


@router.get("/{auction_id}/bids", response_model=SuccessEnvelope[list[BidResponse]])
async def list_bids(
    auction_id: UUID,
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
    gateway: Gateway = Depends(get_gateway),
    broker: Broker = Depends(get_broker),
) -> dict[str, Any]:
    bids = await BidService(session, gateway, broker).history(auction_id, limit=limit)
    return success(bids, "Bids retrieved")
