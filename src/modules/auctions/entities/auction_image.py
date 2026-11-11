import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.base import Base

if TYPE_CHECKING:
    from src.modules.auctions.entities.auction import Auction


class AuctionImage(Base):
    """One uploaded image belonging to an auction.

    Both ``key`` (the object key inside the bucket) and ``url`` (its public
    address) are stored, so the row can be re-pointed or cleaned up later
    without reconstructing either value from the other.
    """

    __tablename__ = "auction_images"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    auction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("auctions.id", ondelete="CASCADE"), index=True, nullable=False
    )

    key: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    # Display order; the lowest position is the auction's cover image.
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    auction: Mapped["Auction"] = relationship(back_populates="images")

    __table_args__ = (Index("ix_auction_images_auction_position", "auction_id", "position"),)
