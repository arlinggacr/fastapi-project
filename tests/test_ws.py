"""WebSocket behaviour."""

from __future__ import annotations

import pytest
from starlette.websockets import WebSocketDisconnect

pytestmark = pytest.mark.integration


def test_snapshot_for_anonymous_viewer(client, auction):
    created = auction()
    with client.websocket_connect(f"/ws/auctions/{created['id']}") as ws:
        message = ws.receive_json()
    assert message["type"] == "snapshot"
    assert message["data"]["current_price"] == "100.00"
    assert message["data"]["you"] is None


def test_snapshot_includes_identity(client, auction, make_user):
    created = auction()
    viewer = make_user()
    with client.websocket_connect(f"/ws/auctions/{created['id']}?token={viewer['token']}") as ws:
        message = ws.receive_json()
    assert message["data"]["you"]["username"] == viewer["username"]
    assert message["data"]["you"]["is_seller"] is False


def test_live_bid_is_pushed(client, auction, make_user):
    created = auction()
    bidder = make_user()
    with client.websocket_connect(f"/ws/auctions/{created['id']}?token={bidder['token']}") as ws:
        assert ws.receive_json()["type"] == "snapshot"
        response = client.post(
            f"/auctions/{created['id']}/bids",
            json={"amount": "100.00"},
            headers=bidder["headers"],
        )
        assert response.status_code == 201
        event = ws.receive_json()
    assert event["type"] == "bid_placed"
    assert event["data"]["amount"] == "100.00"


def test_user_socket_requires_auth(client):
    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws/me") as ws:
        ws.receive_json()


def test_unknown_auction_closes_socket(client):
    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect("/ws/auctions/00000000-0000-0000-0000-000000000000") as ws,
    ):
        ws.receive_json()
