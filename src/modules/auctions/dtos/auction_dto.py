"""Request DTOs for the auctions module."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator, model_validator

from src.common.constants.enums import AuctionStatus
from src.utils.sanitize import clean_text, clean_url

MAX_PRICE = Decimal("9999999999.99")


class AuctionCreateDTO(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(default="", max_length=5000)
    category: str = Field(default="general", min_length=2, max_length=64)
    image_url: str | None = Field(default=None, max_length=1024)

    starting_price: Decimal = Field(gt=0, le=MAX_PRICE, max_digits=12, decimal_places=2)
    min_increment: Decimal = Field(gt=0, le=MAX_PRICE, max_digits=12, decimal_places=2)

    start_time: datetime
    end_time: datetime

    @field_validator("title", "description")
    @classmethod
    def _clean_text(cls, value: str) -> str:
        return clean_text(value, max_length=5000)

    @field_validator("category")
    @classmethod
    def _clean_category(cls, value: str) -> str:
        cleaned = clean_text(value, max_length=64).lower()
        if not cleaned:
            raise ValueError("category must not be blank")
        return cleaned

    @field_validator("image_url")
    @classmethod
    def _clean_image(cls, value: str | None) -> str | None:
        return clean_url(value)

    @model_validator(mode="after")
    def _check_window(self) -> "AuctionCreateDTO":
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        return self


class AuctionUpdateDTO(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    category: str | None = Field(default=None, min_length=2, max_length=64)
    image_url: str | None = Field(default=None, max_length=1024)
    start_time: datetime | None = None
    end_time: datetime | None = None

    @field_validator("title", "description")
    @classmethod
    def _clean_text(cls, value: str | None) -> str | None:
        return None if value is None else clean_text(value, max_length=5000)

    @field_validator("category")
    @classmethod
    def _clean_category(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = clean_text(value, max_length=64).lower()
        if not cleaned:
            raise ValueError("category must not be blank")
        return cleaned

    @field_validator("image_url")
    @classmethod
    def _clean_image(cls, value: str | None) -> str | None:
        return clean_url(value)


class AuctionQueryDTO(BaseModel):
    status: AuctionStatus | None = None
    category: str | None = Field(default=None, max_length=64)
    q: str | None = Field(default=None, max_length=100)

    @field_validator("category", "q")
    @classmethod
    def _clean(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = clean_text(value, max_length=100)
        return cleaned or None
