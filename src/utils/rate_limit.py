"""Small Redis-backed rate limiter.

Fixed-window counters: ``INCR`` then set the TTL on the first hit. Enough to
stop credential stuffing and bid spam without adding another dependency.
"""

from __future__ import annotations

from src.core.redis import Gateway


async def hit(gateway: Gateway, key: str, *, limit: int, window_seconds: int) -> bool:
    """Record one hit. Returns ``False`` when the caller is over the limit."""
    count = await gateway.incr(key)
    if count == 1:
        await gateway.expire(key, window_seconds)
    return count <= limit
