"""Background scheduler: starts and ends auctions on time.

Computes the next due timestamp and sleeps until then (capped at 30s) so the
database is not polled every second.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from src.core.realtime import Broker
from src.core.redis import Gateway
from src.core.time import utcnow
from src.database.session import SessionLocal
from src.modules.auctions.repositories.auction_repository import AuctionRepository
from src.modules.auctions.services.lifecycle_service import AuctionLifecycleService

logger = logging.getLogger(__name__)

MAX_SLEEP = 30.0
MIN_SLEEP = 0.5


class AuctionScheduler:
    def __init__(self, gateway: Gateway, broker: Broker) -> None:
        self._gateway = gateway
        self._broker = broker
        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stopping.clear()
            self._task = asyncio.create_task(self._run(), name="auction-scheduler")

    async def stop(self) -> None:
        self._stopping.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def tick(self) -> tuple[int, int]:
        """One pass: activate due auctions, finalize expired ones.

        Returns ``(activated, finalized)``. The caller logs a single summary
        line, so draining a backlog does not emit one line per auction.
        """
        now = utcnow()
        activated = 0
        finalized = 0
        async with SessionLocal() as session:
            repo = AuctionRepository(session)
            lifecycle = AuctionLifecycleService(session, self._gateway, self._broker)

            for auction in await repo.due_to_start(now):
                try:
                    if await lifecycle.activate(auction):
                        activated += 1
                except Exception:
                    logger.exception("failed to activate auction %s", auction.id)
                    await repo.rollback()

            for auction in await repo.due_to_end(now):
                try:
                    if await lifecycle.finalize(auction):
                        finalized += 1
                except Exception:
                    logger.exception("failed to finalize auction %s", auction.id)
                    await repo.rollback()

        if activated or finalized:
            logger.info("scheduler pass: %d started, %d ended", activated, finalized)
        return activated, finalized

    async def _run(self) -> None:
        logger.info("auction scheduler started")
        while not self._stopping.is_set():
            try:
                await self.tick()
                delay = await self._next_delay()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("scheduler tick failed")
                delay = 5.0
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=delay)
            except TimeoutError:
                pass
        logger.info("auction scheduler stopped")

    async def _next_delay(self) -> float:
        async with SessionLocal() as session:
            repo = AuctionRepository(session)
            start = await repo.next_start_time()
            end = await repo.next_end_time()

        now = utcnow()
        candidates = [value for value in (start, end) if value is not None]
        if not candidates:
            return MAX_SLEEP
        delta = min((_aware(value) - now).total_seconds() for value in candidates)
        return max(MIN_SLEEP, min(delta, MAX_SLEEP))


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)
