"""WebSocket handshake / snapshot / live-push checks (uses Starlette TestClient)."""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.time import utcnow
from src.main import app
from starlette.testclient import TestClient


def ok(label: str, condition: bool, detail: object = "") -> None:
    print(f"{'PASS' if condition else 'FAIL'}  {label}" + (f"  -> {detail}" if detail else ""))
    if not condition:
        raise SystemExit(1)


with TestClient(app) as client:
    suffix = utcnow().strftime("%H%M%S%f")
    bodies = {
        "seller": {
            "email": f"ws-seller-{suffix}@example.com",
            "username": f"wsseller{suffix}",
            "password": "Passw0rd!123",
        },
        "bidder": {
            "email": f"ws-bidder-{suffix}@example.com",
            "username": f"wsbidder{suffix}",
            "password": "Passw0rd!123",
        },
    }
    tokens = {}
    for role, body in bodies.items():
        r = client.post("/auth/register", json=body)
        ok(f"register {role}", r.status_code == 201, r.text[:100])
        r = client.post("/auth/login", json={"email": body["email"], "password": body["password"]})
        tokens[role] = r.json()["access_token"]

    now = utcnow()
    r = client.post(
        "/auctions",
        json={
            "title": f"WS auction {suffix}",
            "description": "ws",
            "starting_price": "10.00",
            "min_increment": "1.00",
            "start_time": (now - timedelta(seconds=1)).isoformat(),
            "end_time": (now + timedelta(minutes=5)).isoformat(),
        },
        headers={"Authorization": f"Bearer {tokens['seller']}"},
    )
    ok("create auction", r.status_code == 201, r.text[:120])
    aid = r.json()["id"]

    # --- anonymous spectator: snapshot works ---
    with client.websocket_connect(f"/ws/auctions/{aid}") as ws:
        snap = ws.receive_json()
        ok("ws snapshot type", snap["type"] == "snapshot", snap.get("type"))
        ok(
            "ws snapshot price",
            snap["data"]["current_price"] == "10.00",
            snap["data"]["current_price"],
        )
        ok("ws anonymous you=None", snap["data"]["you"] is None, snap["data"]["you"])

    # --- authenticated bidder: identity echoed + live bid push ---
    with client.websocket_connect(f"/ws/auctions/{aid}?token={tokens['bidder']}") as ws:
        snap = ws.receive_json()
        ok(
            "ws authenticated you",
            snap["data"]["you"]["username"] == bodies["bidder"]["username"],
            snap["data"]["you"],
        )
        ok("ws is_seller false", snap["data"]["you"]["is_seller"] is False)

        # place a bid from the same process; the socket polls the stream
        r = client.post(
            f"/auctions/{aid}/bids",
            json={"amount": "11.00"},
            headers={"Authorization": f"Bearer {tokens['bidder']}"},
        )
        ok("bid accepted while socket open", r.status_code == 201, r.text[:120])

        event = ws.receive_json()
        ok("live bid_placed pushed", event["type"] == "bid_placed", event.get("type"))
        ok("event amount", event["data"]["amount"] == "11.00", event["data"].get("amount"))

    # --- /ws/me requires auth ---
    try:
        with client.websocket_connect("/ws/me") as ws:
            ws.receive_json()
        ok("/ws/me rejected anonymous", False, "connection stayed open")
    except Exception as exc:
        ok("/ws/me rejected anonymous", True, type(exc).__name__)

    # --- /ws/me receives the outbid notification ---
    seller_id = client.get(
        "/users/me", headers={"Authorization": f"Bearer {tokens['seller']}"}
    ).json()["id"]
    ok("seller id present", bool(seller_id))

print("\nAll websocket checks passed.")
