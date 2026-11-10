from decimal import Decimal

import pytest
from src.core.money import from_cents, to_cents


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("10.00", 1000),
        ("10.005", 1001),
        ("0.01", 1),
        (Decimal("99.99"), 9999),
        (5, 500),
    ],
)
def test_to_cents(value, expected):
    assert to_cents(value) == expected


@pytest.mark.parametrize(
    ("cents", "expected"),
    [(1000, "10.00"), (1, "0.01"), (9999, "99.99"), (0, "0.00")],
)
def test_from_cents(cents, expected):
    assert str(from_cents(cents)) == expected


def test_round_trip_keeps_precision():
    for raw in ("0.01", "123.45", "999999.99"):
        assert str(from_cents(to_cents(raw))) == raw
