"""Verifies the realtime pipeline and scheduler transitions.

Usage:  .venv/bin/python scripts/smoke_realtime.py
"""

from __future__ import annotations

import asyncio
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from src.core.config import get_settings
from src.core.keys import events_key, user_events_key
from src.core.realtime import Broker
from src.core.time import utcnow
from src.database.session import SessionLocal
from src.main import app
from src.modules.auctions.repositories.auction_repository import AuctionRepository
from src.modules.auctions.services.scheduler import AuctionScheduler


def ok(label: str, condition: bool, detail: object = "") -> None:
    print(f"{'PASS' if condition else 'FAIL'}  {label}" + (f"  -> {detail}" if detail else ""))
    if not condition:
        raise SystemExit(1)


async def main() -> None:
    settings = get_settings()
    print(f"redis backend: {settings.redis_mode}")
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test", timeout=30
        ) as client:
            suffix = utcnow().strftime("%H%M%S%f")
            users = {}
            for role in ("seller", "bidder", "watcher"):
                body = {
                    "email": f"rt-{role}-{suffix}@example.com",
                    "username": f"rt{role}{suffix}",
                    "password": "Passw0rd!123",
                }
                await client.post("/auth/register", json=body)
                r = await client.post(
                    "/auth/login", json={"email": body["email"], "password": body["password"]}
                )
                users[role] = (r.json()["data"]["access_token"], r.json()["data"]["access_token"])

            me = {}
            for role, (token, _) in users.items():
                r = await client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
                me[role] = r.json()["data"]["id"]

            sh = {"Authorization": f"Bearer {users['seller'][0]}"}
            bh = {"Authorization": f"Bearer {users['bidder'][0]}"}
            wh = {"Authorization": f"Bearer {users['watcher'][0]}"}

            # --- auction scheduled 3s from now ---
            now = utcnow()
            payload = {
                "title": f"RT auction {suffix}",
                "description": "realtime",
                "starting_price": "50.00",
                "min_increment": "5.00",
                "start_time": (now + timedelta(seconds=3)).isoformat(),
                "end_time": (now + timedelta(seconds=40)).isoformat(),
            }
            r = await client.post("/auctions", json=payload, headers=sh)
            ok("create scheduled auction", r.status_code == 201, r.text[:160])
            auction = r.json()["data"]
            aid = auction["id"]
            ok("status is scheduled", auction["status"] == "scheduled", auction["status"])

            # watcher subscribes
            await client.post(f"/auctions/{aid}/watch", headers=wh)

            gateway = app.state.gateway
            broker = Broker(gateway, poll_interval=0.2)

            # --- listen on both streams before the transition ---
            auction_events: list[dict] = []
            user_events: list[dict] = []

            async def collect(stream: str, sink: list[dict], last_id: str, duration: float) -> None:
                async def _loop() -> None:
                    async for event in broker.listen(stream, last_id=last_id):
                        sink.append(event)

                try:
                    await asyncio.wait_for(_loop(), timeout=duration)
                except TimeoutError:
                    pass

            a_last = await gateway.xlast_id(events_key(aid))
            u_last = await gateway.xlast_id(user_events_key(me["watcher"]))
            tasks = [
                asyncio.create_task(collect(events_key(aid), auction_events, a_last, 8)),
                asyncio.create_task(
                    collect(user_events_key(me["watcher"]), user_events, u_last, 8)
                ),
            ]

            # --- scheduler flips scheduled -> active ---
            scheduler = AuctionScheduler(gateway, broker)
            await asyncio.sleep(3.5)
            await scheduler.tick()

            await asyncio.gather(*tasks)

            r = await client.get(f"/auctions/{aid}")
            ok("auction now active", r.json()["data"]["status"] == "active", r.json()["data"]["status"])
            ok(
                "auction_started broadcast on auction stream",
                any(e["type"] == "auction_started" for e in auction_events),
                [e["type"] for e in auction_events],
            )
            ok(
                "watcher got auction_started notification",
                any(e["type"] == "auction_started" for e in user_events),
                [e["type"] for e in user_events],
            )

            # --- bid, then verify bid_placed lands on the stream ---
            a_last = await gateway.xlast_id(events_key(aid))
            r = await client.post(f"/auctions/{aid}/bids", json={"amount": "55.00"}, headers=bh)
            ok("bid accepted", r.status_code == 201, r.text[:160])

            bid_events: list[dict] = []
            await collect(events_key(aid), bid_events, a_last, 3)
            ok(
                "bid_placed broadcast",
                any(e["type"] == "bid_placed" for e in bid_events),
                [e["type"] for e in bid_events],
            )

            # --- force end via scheduler path ---
            async with SessionLocal() as session:
                row = await AuctionRepository(session).get_by_id(__import__("uuid").UUID(aid))
                row.end_time = utcnow() - timedelta(seconds=1)
                await session.commit()
            await scheduler.tick()
            r = await client.get(f"/auctions/{aid}")
            ok("auction ended", r.json()["data"]["status"] == "ended", r.json()["data"]["status"])
            ok(
                "winner recorded",
                r.json()["data"]["current_winner_id"] == me["bidder"],
                r.json()["data"]["current_winner_id"],
            )

            notifs = (await client.get("/notifications", headers=wh)).json()["data"]
            types = [n["type"] for n in notifs]
            ok(
                "watcher notified of start and end",
                "auction_started" in types and "auction_ended" in types,
                types,
            )

    print("\nAll realtime checks passed.")


if __name__ == "__main__":
    asyncio.run(main())
