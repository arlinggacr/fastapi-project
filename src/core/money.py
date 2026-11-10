"""Money helpers.

Amounts are stored as integer **cents** everywhere (Redis, Lua scripts) to
avoid floating point drift, and exposed as ``Decimal`` at the API boundary.
"""

from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


def to_cents(value: Decimal | int | float | str) -> int:
    return int((Decimal(str(value)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def from_cents(cents: int | str) -> Decimal:
    return (Decimal(int(cents)) / 100).quantize(CENT)


def format_money(value: Decimal | int | float | str) -> str:
    return f"{from_cents(to_cents(value)):.2f}"
