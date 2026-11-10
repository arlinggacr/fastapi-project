from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from src.common.constants.enums import AuctionStatus
from src.modules.users.dtos.user_response import PublicUserResponse


class AuctionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    description: str
    category: str
    image_url: str | None

    starting_price: Decimal
    min_increment: Decimal
    current_price: Decimal
    min_next_bid: Decimal
    current_winner_id: UUID | None

    status: AuctionStatus
    start_time: datetime
    end_time: datetime
    extended_count: int

    seller: PublicUserResponse
    bid_count: int = 0
    watchers: int = 0
    is_seller: bool = False
    is_watching: bool = False
    created_at: datetime


class AuctionPageResponse(BaseModel):
    items: list[AuctionResponse]
    total: int
    page: int
    page_size: int
