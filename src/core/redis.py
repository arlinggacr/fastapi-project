"""Redis access layer.

Two interchangeable backends behind a single small interface:

* :class:`RespGateway` - native ``redis://`` / ``rediss://`` (Upstash TCP).
  Supports real pub/sub push.
* :class:`RestGateway` - Upstash REST API (HTTP). No pub/sub, so the
  realtime layer polls a Redis Stream instead.

The application only uses the handful of commands declared in
:class:`Gateway`, which keeps both implementations honest and small.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable

import httpx
import redis.asyncio as aioredis

from src.core.config import Settings

logger = logging.getLogger(__name__)


@runtime_checkable
class Gateway(Protocol):
    supports_pubsub: bool

    async def ping(self) -> bool: ...
    async def eval(self, script: str, keys: list[str], args: list[Any]) -> Any: ...
    async def hgetall(self, key: str) -> dict[str, str]: ...
    async def hset(self, key: str, mapping: dict[str, Any]) -> None: ...
    async def delete(self, *keys: str) -> None: ...
    async def set(
        self, key: str, value: str, *, nx: bool = False, px: int | None = None
    ) -> bool: ...
    async def xadd(self, key: str, fields: dict[str, Any], maxlen: int = 1000) -> str: ...
    async def xrange(
        self, key: str, start: str = "-", end: str = "+", count: int = 100
    ) -> list[tuple[str, dict[str, str]]]: ...
    async def xlast_id(self, key: str) -> str: ...
    async def sadd(self, key: str, *members: str) -> int: ...
    async def srem(self, key: str, *members: str) -> int: ...
    async def sismember(self, key: str, member: str) -> bool: ...
    async def scard(self, key: str) -> int: ...
    async def smembers(self, key: str) -> set[str]: ...
    async def expire(self, key: str, seconds: int) -> bool: ...
    async def incr(self, key: str) -> int: ...
    async def publish(self, channel: str, message: str) -> None: ...
    def subscribe(self, channel: str) -> AsyncIterator[dict[str, Any]]: ...
    async def close(self) -> None: ...


class RespGateway:
    """Native Redis protocol backend (supports pub/sub)."""

    supports_pubsub = True

    def __init__(self, url: str) -> None:
        self._redis = aioredis.Redis.from_url(url, decode_responses=True)

    async def ping(self) -> bool:
        return bool(await self._redis.ping())

    async def eval(self, script: str, keys: list[str], args: list[Any]) -> Any:
        return await self._redis.eval(script, len(keys), *keys, *[str(a) for a in args])

    async def hgetall(self, key: str) -> dict[str, str]:
        return await self._redis.hgetall(key)

    async def hset(self, key: str, mapping: dict[str, Any]) -> None:
        await self._redis.hset(key, mapping={k: str(v) for k, v in mapping.items()})

    async def delete(self, *keys: str) -> None:
        if keys:
            await self._redis.delete(*keys)

    async def set(self, key: str, value: str, *, nx: bool = False, px: int | None = None) -> bool:
        result = await self._redis.set(key, value, nx=nx, px=px)
        return bool(result)

    async def xadd(self, key: str, fields: dict[str, Any], maxlen: int = 1000) -> str:
        return await self._redis.xadd(
            key, {k: str(v) for k, v in fields.items()}, maxlen=maxlen, approximate=True
        )

    async def xrange(
        self, key: str, start: str = "-", end: str = "+", count: int = 100
    ) -> list[tuple[str, dict[str, str]]]:
        rows = await self._redis.xrange(key, min=start, max=end, count=count)
        return [(row_id, dict(fields)) for row_id, fields in rows]

    async def xlast_id(self, key: str) -> str:
        rows = await self._redis.xrevrange(key, count=1)
        return rows[0][0] if rows else "-"

    async def sadd(self, key: str, *members: str) -> int:
        return await self._redis.sadd(key, *members)

    async def srem(self, key: str, *members: str) -> int:
        return await self._redis.srem(key, *members)

    async def sismember(self, key: str, member: str) -> bool:
        return bool(await self._redis.sismember(key, member))

    async def scard(self, key: str) -> int:
        return await self._redis.scard(key)

    async def smembers(self, key: str) -> set[str]:
        return set(await self._redis.smembers(key))

    async def expire(self, key: str, seconds: int) -> bool:
        return bool(await self._redis.expire(key, seconds))

    async def incr(self, key: str) -> int:
        return int(await self._redis.incr(key))

    async def publish(self, channel: str, message: str) -> None:
        await self._redis.publish(channel, message)

    async def subscribe(self, channel: str) -> AsyncIterator[dict[str, Any]]:
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(channel)
        try:
            async for message in pubsub.listen():
                if message.get("type") == "message":
                    try:
                        yield json.loads(message["data"])
                    except (TypeError, json.JSONDecodeError):
                        logger.warning("dropping malformed pub/sub message on %s", channel)
        finally:
            try:
                await pubsub.unsubscribe(channel)
                await pubsub.aclose()
            except Exception:  # pragma: no cover - best effort cleanup
                pass

    async def close(self) -> None:
        await self._redis.aclose()


class RestGateway:
    """Upstash REST backend.

    Every call is a single HTTP request carrying a Redis command array.
    ``supports_pubsub`` is ``False``: the realtime layer polls streams.
    """

    supports_pubsub = False

    def __init__(self, url: str, token: str, timeout: float = 10.0) -> None:
        self._url = url.rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={"Authorization": f"Bearer {token}"},
        )

    async def _cmd(self, *args: Any) -> Any:
        response = await self._client.post(self._url, json=[str(a) for a in args])
        response.raise_for_status()
        data = response.json()
        if data.get("error"):
            raise RuntimeError(f"upstash: {data['error']}")
        return data.get("result")

    async def ping(self) -> bool:
        return (await self._cmd("PING")) == "PONG"

    async def eval(self, script: str, keys: list[str], args: list[Any]) -> Any:
        return await self._cmd("EVAL", script, len(keys), *keys, *[str(a) for a in args])

    async def hgetall(self, key: str) -> dict[str, str]:
        flat = await self._cmd("HGETALL", key) or []
        return dict(zip(flat[::2], flat[1::2], strict=False))

    async def hset(self, key: str, mapping: dict[str, Any]) -> None:
        flat: list[str] = []
        for field, value in mapping.items():
            flat.extend([field, str(value)])
        await self._cmd("HSET", key, *flat)

    async def delete(self, *keys: str) -> None:
        if keys:
            await self._cmd("DEL", *keys)

    async def set(self, key: str, value: str, *, nx: bool = False, px: int | None = None) -> bool:
        args: list[Any] = ["SET", key, value]
        if nx:
            args.append("NX")
        if px:
            args.extend(["PX", px])
        return (await self._cmd(*args)) == "OK"

    async def xadd(self, key: str, fields: dict[str, Any], maxlen: int = 1000) -> str:
        flat: list[str] = []
        for field, value in fields.items():
            flat.extend([field, str(value)])
        return await self._cmd("XADD", key, "MAXLEN", "~", maxlen, "*", *flat)

    async def xrange(
        self, key: str, start: str = "-", end: str = "+", count: int = 100
    ) -> list[tuple[str, dict[str, str]]]:
        rows = await self._cmd("XRANGE", key, start, end, "COUNT", count) or []
        parsed: list[tuple[str, dict[str, str]]] = []
        for row in rows:
            row_id, flat = row[0], row[1]
            parsed.append((row_id, dict(zip(flat[::2], flat[1::2], strict=False))))
        return parsed

    async def xlast_id(self, key: str) -> str:
        rows = await self._cmd("XREVRANGE", key, "+", "-", "COUNT", 1) or []
        return rows[0][0] if rows else "-"

    async def sadd(self, key: str, *members: str) -> int:
        return int(await self._cmd("SADD", key, *members) or 0)

    async def srem(self, key: str, *members: str) -> int:
        return int(await self._cmd("SREM", key, *members) or 0)

    async def sismember(self, key: str, member: str) -> bool:
        return bool(await self._cmd("SISMEMBER", key, member))

    async def scard(self, key: str) -> int:
        return int(await self._cmd("SCARD", key) or 0)

    async def smembers(self, key: str) -> set[str]:
        return set(await self._cmd("SMEMBERS", key) or [])

    async def expire(self, key: str, seconds: int) -> bool:
        return bool(await self._cmd("EXPIRE", key, seconds))

    async def incr(self, key: str) -> int:
        return int(await self._cmd("INCR", key) or 0)

    async def publish(self, channel: str, message: str) -> None:
        await self._cmd("PUBLISH", channel, message)

    async def subscribe(self, channel: str) -> AsyncIterator[dict[str, Any]]:
        raise NotImplementedError("pub/sub is not available over the Upstash REST API")
        yield  # pragma: no cover - makes this an async generator

    async def close(self) -> None:
        await self._client.aclose()


def create_gateway(settings: Settings) -> Gateway:
    if settings.redis_url:
        logger.info("redis backend: native pub/sub (%s)", settings.redis_url.split("@")[-1])
        return RespGateway(settings.redis_url)
    if settings.upstash_redis_rest_url and settings.upstash_redis_rest_token:
        logger.info("redis backend: upstash REST (stream polling)")
        return RestGateway(settings.upstash_redis_rest_url, settings.upstash_redis_rest_token)
    raise RuntimeError(
        "No Redis configured. Set REDIS_URL (rediss://...) or "
        "UPSTASH_REDIS_REST_URL + UPSTASH_REDIS_REST_TOKEN in .env"
    )
