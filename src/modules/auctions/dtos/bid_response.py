from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from src.modules.users.dtos.user_response import PublicUserResponse


class BidResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    auction_id: UUID
    bidder_id: UUID
    amount: Decimal
    created_at: datetime
    bidder: PublicUserResponse | None = None


class BidAcceptedResponse(BaseModel):
    bid: BidResponse
    current_price: Decimal
    min_next_bid: Decimal
    end_time: datetime
    extended: bool
    bid_count: int
