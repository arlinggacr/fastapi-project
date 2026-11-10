from decimal import Decimal

from pydantic import BaseModel, Field, field_validator


class BidCreateDTO(BaseModel):
    amount: Decimal = Field(gt=0, le=Decimal("9999999999.99"), max_digits=12, decimal_places=2)

    @field_validator("amount")
    @classmethod
    def _two_places(cls, value: Decimal) -> Decimal:
        exponent = value.as_tuple().exponent
        if isinstance(exponent, int) and exponent < -2:
            raise ValueError("amount supports at most 2 decimal places")
        return value
