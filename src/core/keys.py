"""Central place for every Redis key / channel name."""

from uuid import UUID

from src.core.config import get_settings


def _prefix() -> str:
    return get_settings().key_prefix


def state_key(auction_id: UUID | str) -> str:
    """Hash with the live auction state (price, top bidder, end time...)."""
    return f"{_prefix()}:auction:{auction_id}:state"


def events_key(auction_id: UUID | str) -> str:
    """Redis stream + pub/sub channel for one auction."""
    return f"{_prefix()}:auction:{auction_id}:events"


def user_events_key(user_id: UUID | str) -> str:
    return f"{_prefix()}:user:{user_id}:events"


def feed_key() -> str:
    return f"{_prefix()}:feed:events"


def lock_key(name: str) -> str:
    return f"{_prefix()}:lock:{name}"
