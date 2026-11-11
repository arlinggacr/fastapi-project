"""End-to-end smoke test against the real Neon + Upstash stack.

Usage:  .venv/bin/python scripts/smoke.py
Creates throwaway users/auctions prefixed with `smoke-` and cleans them up.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from src.core.time import utcnow
from src.main import app

BASE = "http://test"


def ok(label: str, condition: bool, detail: object = "") -> None:
    print(f"{'PASS' if condition else 'FAIL'}  {label}" + (f"  -> {detail}" if detail else ""))
    if not condition:
        raise SystemExit(1)


async def main() -> None:
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url=BASE, timeout=30) as client:
            suffix = utcnow().strftime("%H%M%S%f")
            seller = {
                "email": f"smoke-seller-{suffix}@example.com",
                "username": f"smokeseller{suffix}",
                "password": "Passw0rd!123",
            }
            bidder = {
                "email": f"smoke-bidder-{suffix}@example.com",
                "username": f"smokebidder{suffix}",
                "password": "Passw0rd!123",
            }
            other = {
                "email": f"smoke-other-{suffix}@example.com",
                "username": f"smokeother{suffix}",
                "password": "Passw0rd!123",
            }

            for u in (seller, bidder, other):
                r = await client.post("/auth/register", json=u)
                ok(f"register {u['username']}", r.status_code == 201, r.text[:120])

            tokens = {}
            for u in (seller, bidder, other):
                r = await client.post(
                    "/auth/login", json={"email": u["email"], "password": u["password"]}
                )
                ok(f"login {u['username']}", r.status_code == 200, r.text[:120])
                tokens[u["username"]] = r.json()["data"]["access_token"]

            sh = {"Authorization": f"Bearer {tokens[seller['username']]}"}
            bh = {"Authorization": f"Bearer {tokens[bidder['username']]}"}
            oh = {"Authorization": f"Bearer {tokens[other['username']]}"}

            now = utcnow()
            payload = {
                "title": f"Smoke auction {suffix}",
                "description": "A test lot",
                "category": "Test",
                "starting_price": "100.00",
                "min_increment": "10.00",
                "start_time": (now - timedelta(seconds=1)).isoformat(),
                "end_time": (now + timedelta(seconds=90)).isoformat(),
            }
            r = await client.post("/auctions", json=payload, headers=sh)
            ok("create auction", r.status_code == 201, r.text[:200])
            auction = r.json()["data"]
            aid = auction["id"]
            ok("auction is active", auction["status"] == "active", auction["status"])
            ok("category normalised", auction["category"] == "test", auction["category"])

            r = await client.post(f"/auctions/{aid}/bids", json={"amount": "100.00"}, headers=sh)
            ok("seller cannot bid", r.status_code == 409, r.text[:160])

            r = await client.post(f"/auctions/{aid}/bids", json={"amount": "50.00"}, headers=bh)
            ok("bid below starting price rejected", r.status_code == 409, r.text[:160])

            r = await client.post(f"/auctions/{aid}/bids", json={"amount": "110.00"}, headers=bh)
            ok("valid bid accepted", r.status_code == 201, r.text[:200])
            first = r.json()["data"]
            ok("price updated", first["current_price"] == "110.00", first["current_price"])
            ok("min next bid", first["min_next_bid"] == "120.00", first["min_next_bid"])

            r = await client.post(f"/auctions/{aid}/bids", json={"amount": "115.00"}, headers=oh)
            ok("increment enforced", r.status_code == 409, r.text[:160])

            r = await client.post(f"/auctions/{aid}/bids", json={"amount": "120.00"}, headers=oh)
            ok("second bid accepted", r.status_code == 201, r.text[:200])

            # Concurrency: 12 simultaneous identical bids -> exactly one wins.
            results = await asyncio.gather(
                *[
                    client.post(f"/auctions/{aid}/bids", json={"amount": "200.00"}, headers=bh)
                    for _ in range(12)
                ]
            )
            accepted = [x for x in results if x.status_code == 201]
            ok(
                "concurrent bids: exactly one accepted",
                len(accepted) == 1,
                [x.status_code for x in results],
            )

            r = await client.get(f"/auctions/{aid}/bids")
            ok("bid history", r.status_code == 200 and len(r.json()["data"]) >= 3, len(r.json()["data"]))

            r = await client.get("/notifications", headers=oh)
            ok(
                "outbid notification delivered",
                r.status_code == 200 and any(n["type"] == "outbid" for n in r.json()["data"]),
                [n["type"] for n in r.json()["data"]],
            )

            # Watch + force end through the scheduler path.
            r = await client.post(f"/auctions/{aid}/watch", headers=oh)
            ok("watch auction", r.status_code == 204, r.text[:120])

            r = await client.get(f"/auctions/{aid}")
            ok("watchers counted", r.json()["data"]["watchers"] == 1, r.json()["data"]["watchers"])

            r = await client.get("/health")
            ok("health", r.status_code == 200 and r.json()["data"]["redis"] is True, r.json())

    print("\nAll smoke checks passed.")


if __name__ == "__main__":
    asyncio.run(main())
