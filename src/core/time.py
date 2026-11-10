from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)


def to_ms(value: datetime) -> int:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return int(value.timestamp() * 1000)


def from_ms(value: int | str) -> datetime:
    return datetime.fromtimestamp(int(value) / 1000, tz=UTC)


def now_ms() -> int:
    return to_ms(utcnow())
