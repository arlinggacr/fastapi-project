"""Realtime event fan-out.

Every event is appended to a Redis Stream (durable, replayable) and, when the
backend supports it, also published on a pub/sub channel for instant push.

* Native Redis  -> WebSockets get pub/sub messages (sub-millisecond).
* Upstash REST  -> WebSockets poll the stream every ``poll_interval`` seconds.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from src.core.redis import Gateway
from src.core.time import now_ms

logger = logging.getLogger(__name__)


class Broker:
    def __init__(self, gateway: Gateway, poll_interval: float = 0.5) -> None:
        self._gateway = gateway
        self._poll_interval = poll_interval

    async def publish(self, stream: str, event: dict[str, Any]) -> dict[str, Any]:
        """Persist an event to the stream and push it to live listeners."""
        event = {**event, "ts": event.get("ts") or now_ms()}
        payload = json.dumps(event, separators=(",", ":"), default=str)
        event_id = await self._gateway.xadd(stream, {"type": event["type"], "payload": payload})
        event["id"] = event_id
        if self._gateway.supports_pubsub:
            await self._gateway.publish(stream, payload)
        return event

    async def listen(self, stream: str, last_id: str = "-") -> AsyncIterator[dict[str, Any]]:
        """Yield events after ``last_id`` forever (cancellable)."""
        if self._gateway.supports_pubsub:
            async for event in self._gateway.subscribe(stream):
                yield event
            return

        cursor = last_id
        while True:
            start = "-" if cursor in ("", "-", "$") else f"({cursor}"
            rows = await self._gateway.xrange(stream, start)
            for event_id, fields in rows:
                cursor = event_id
                try:
                    event = json.loads(fields["payload"])
                except (KeyError, json.JSONDecodeError):
                    logger.warning("dropping malformed stream entry %s", event_id)
                    continue
                event["id"] = event_id
                yield event
            await asyncio.sleep(self._poll_interval)
