"""Admin routes: /admin/* (every route requires the admin role)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.constants.enums import AuctionStatus
from src.common.responses import conflict, not_found
from src.core.realtime import Broker
from src.core.redis import Gateway
from src.database.session import get_session
from src.modules.auctions.dtos.auction_response import AuctionResponse
from src.modules.auctions.repositories.auction_repository import AuctionRepository
from src.modules.auctions.repositories.bid_repository import BidRepository
from src.modules.auctions.services.auction_service import AuctionService
from src.modules.auctions.services.lifecycle_service import AuctionLifecycleService
from src.modules.users.dtos.user_dto import UserUpdateRoleDTO
from src.modules.users.dtos.user_response import UserResponse
from src.modules.users.entities.user import User
from src.modules.users.services.user_service import UserService
from src.utils.deps import get_broker, get_gateway, require_admin
from src.utils.responses import PageHandler, SuccessEnvelope, success

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


@router.get("/users", response_model=SuccessEnvelope[list[UserResponse]])
async def list_users(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    service = UserService(session)
    users = await service.list(page=page, page_size=page_size)
    total = await service.count()
    return success(
        users,
        "Users retrieved",
        PageHandler.build(total_data=total, page=page, page_size=page_size),
    )


@router.patch("/users/{user_id}/role", response_model=SuccessEnvelope[UserResponse])
async def set_role(
    user_id: UUID,
    payload: UserUpdateRoleDTO,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user = await UserService(session).set_role(
        actor=admin, user_id=user_id, role=payload.role
    )
    return success(user, "User role updated")


@router.patch("/users/{user_id}/active", response_model=SuccessEnvelope[UserResponse])
async def set_active(
    user_id: UUID,
    is_active: bool,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user = await UserService(session).set_active(
        actor=admin, user_id=user_id, is_active=is_active
    )
    return success(user, "User activation updated")


@router.post("/auctions/{auction_id}/end", response_model=SuccessEnvelope[AuctionResponse])
async def force_end(
    auction_id: UUID,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
    gateway: Gateway = Depends(get_gateway),
    broker: Broker = Depends(get_broker),
) -> dict[str, Any]:
    repo = AuctionRepository(session)
    auction = await repo.get_by_id(auction_id)
    if auction is None:
        raise not_found("Auction")
    if auction.status != AuctionStatus.active:
        raise conflict("NOT_ACTIVE", "Only active auctions can be ended")

    await AuctionLifecycleService(session, gateway, broker).finalize(auction)
    refreshed = await repo.get_by_id(auction_id)
    if refreshed is None:  # pragma: no cover - defensive
        raise not_found("Auction")
    response = await AuctionService(session, gateway, broker).to_response(
        refreshed, viewer=admin
    )
    return success(response, "Auction ended")


@router.get("/stats", response_model=SuccessEnvelope[dict[str, int]])
async def stats(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    users = UserService(session)
    auctions = AuctionRepository(session)
    bids = BidRepository(session)
    return success(
        {
            "users": await users.count(),
            "auctions": await auctions.count_all(),
            "bids": await bids.count_all(),
            "active_auctions": await auctions.count_by_status(AuctionStatus.active),
        },
        "Platform statistics",
    )


__all__ = ["router", "status"]
