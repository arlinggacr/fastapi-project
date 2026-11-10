"""WebSocket route for a user's personal notifications.

``/ws/me?token=<access_token>`` - requires authentication.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from src.core.keys import user_events_key
from src.core.realtime import Broker
from src.core.redis import Gateway
from src.core.time import now_ms
from src.database.session import SessionLocal
from src.utils.deps import get_user_from_token

logger = logging.getLogger(__name__)
router = APIRouter(tags=["websockets"])

HEARTBEAT_SECONDS = 25


@router.websocket("/ws/me")
async def user_socket(websocket: WebSocket, token: str | None = Query(default=None)) -> None:
    gateway: Gateway = websocket.app.state.gateway
    broker: Broker = websocket.app.state.broker

    if not token:
        await websocket.close(code=4401, reason="Authentication required")
        return

    async with SessionLocal() as session:
        try:
            user = await get_user_from_token(token, session)
        except Exception:
            await websocket.close(code=4401, reason="Authentication required")
            return

    await websocket.accept()
    await websocket.send_json({"type": "ready", "user_id": str(user.id)})

    stop = asyncio.Event()

    async def keepalive() -> None:
        while not stop.is_set():
            await asyncio.sleep(HEARTBEAT_SECONDS)
            if stop.is_set():
                return
            with contextlib.suppress(Exception):
                await websocket.send_json({"type": "ping", "ts": now_ms()})

    heartbeat = asyncio.create_task(keepalive())
    last_id = await gateway.xlast_id(user_events_key(user.id))

    try:
        async for event in broker.listen(user_events_key(user.id), last_id=last_id):
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("user socket failed for %s", user.id)
    finally:
        stop.set()
        heartbeat.cancel()
        with contextlib.suppress(Exception):
            await heartbeat
