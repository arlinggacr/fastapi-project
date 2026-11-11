import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, Text, Uuid, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.common.constants.enums import AuctionStatus
from src.database.base import Base

if TYPE_CHECKING:
    from src.modules.auctions.entities.auction_image import AuctionImage
    from src.modules.auctions.entities.bid import Bid
    from src.modules.users.entities.user import User


class Auction(Base):
    __tablename__ = "auctions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    seller_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    category: Mapped[str] = mapped_column(String(64), default="general", index=True)
    image_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    starting_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    min_increment: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    current_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    current_winner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    status: Mapped[AuctionStatus] = mapped_column(
        SAEnum(
            AuctionStatus, name="auction_status", values_callable=lambda e: [m.value for m in e]
        ),
        default=AuctionStatus.scheduled,
        index=True,
        nullable=False,
    )
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    extended_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    seller: Mapped["User"] = relationship(
        back_populates="auctions", foreign_keys=[seller_id], lazy="selectin"
    )
    bids: Mapped[list["Bid"]] = relationship(
        back_populates="auction", cascade="all, delete-orphan"
    )
    images: Mapped[list["AuctionImage"]] = relationship(
        back_populates="auction",
        cascade="all, delete-orphan",
        order_by="AuctionImage.position",
    )

    __table_args__ = (
        Index("ix_auctions_status_end_time", "status", "end_time"),
        Index("ix_auctions_category_status", "category", "status"),
    )
