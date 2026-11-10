import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.base import Base


class Bid(Base):
    __tablename__ = "bids"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    auction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("auctions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    bidder_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False
    )

    auction: Mapped["Auction"] = relationship(back_populates="bids")  # noqa: F821
    bidder: Mapped["User"] = relationship(  # noqa: F821
        back_populates="bids", foreign_keys=[bidder_id], lazy="selectin"
    )

    __table_args__ = (Index("ix_bids_auction_amount", "auction_id", "amount"),)
