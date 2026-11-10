import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Uuid, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.common.constants.enums import UserRole
from src.database.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, name="user_role", values_callable=lambda e: [m.value for m in e]),
        default=UserRole.user,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Registered centrally in src.database.models, so short names resolve.
    auctions: Mapped[list["Auction"]] = relationship(  # noqa: F821
        back_populates="seller", foreign_keys="Auction.seller_id"
    )
    bids: Mapped[list["Bid"]] = relationship(  # noqa: F821
        back_populates="bidder", foreign_keys="Bid.bidder_id"
    )

    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.admin
