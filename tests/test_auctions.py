"""Auction lifecycle and bidding rules."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

pytestmark = pytest.mark.integration


def _now() -> datetime:
    return datetime.now(UTC)


def test_create_auction_normalises_and_activates(client, auction):
    created = auction()
    assert created["status"] == "active"
    assert created["category"] == "test"
    assert created["current_price"] == "100.00"
    assert created["is_seller"] is True


def test_end_before_start_rejected(client, make_user):
    seller = make_user()
    now = _now()
    response = client.post(
        "/auctions",
        json={
            "title": "Bad window",
            "starting_price": "10.00",
            "min_increment": "1.00",
            "start_time": (now + timedelta(hours=1)).isoformat(),
            "end_time": (now + timedelta(minutes=5)).isoformat(),
        },
        headers=seller["headers"],
    )
    assert response.status_code == 422


def test_past_end_time_rejected(client, make_user):
    seller = make_user()
    now = _now()
    response = client.post(
        "/auctions",
        json={
            "title": "Already over",
            "starting_price": "10.00",
            "min_increment": "1.00",
            "start_time": (now - timedelta(hours=2)).isoformat(),
            "end_time": (now - timedelta(hours=1)).isoformat(),
        },
        headers=seller["headers"],
    )
    assert response.status_code == 422


def test_seller_cannot_bid_on_own_auction(client, auction):
    created = auction()
    seller = auction.seller
    response = client.post(
        f"/auctions/{created['id']}/bids",
        json={"amount": "110.00"},
        headers=seller["headers"],
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "SELLER_CANNOT_BID"


def test_bid_must_meet_starting_price(client, auction, make_user):
    created = auction()
    bidder = make_user()
    response = client.post(
        f"/auctions/{created['id']}/bids",
        json={"amount": "99.99"},
        headers=bidder["headers"],
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "BID_TOO_LOW"
    assert response.json()["detail"]["min_next_bid"] == "100.00"


def test_min_increment_enforced(client, auction, make_user):
    created = auction()
    first = make_user()
    second = make_user()

    assert (
        client.post(
            f"/auctions/{created['id']}/bids",
            json={"amount": "100.00"},
            headers=first["headers"],
        ).status_code
        == 201
    )

    response = client.post(
        f"/auctions/{created['id']}/bids",
        json={"amount": "109.99"},
        headers=second["headers"],
    )
    assert response.status_code == 409
    assert response.json()["detail"]["min_next_bid"] == "110.00"

    accepted = client.post(
        f"/auctions/{created['id']}/bids",
        json={"amount": "110.00"},
        headers=second["headers"],
    )
    assert accepted.status_code == 201
    assert accepted.json()["current_price"] == "110.00"


def test_concurrent_identical_bids_only_one_wins(client, auction, make_user):
    created = auction()
    bidders = [make_user() for _ in range(10)]

    def bid(user):
        return client.post(
            f"/auctions/{created['id']}/bids",
            json={"amount": "200.00"},
            headers=user["headers"],
        ).status_code

    with ThreadPoolExecutor(max_workers=10) as pool:
        statuses = list(pool.map(bid, bidders))

    assert statuses.count(201) == 1, statuses

    bids = client.get(f"/auctions/{created['id']}/bids").json()
    assert len(bids) == 1


def test_outbid_notification(client, auction, make_user):
    created = auction()
    first = make_user()
    second = make_user()

    client.post(
        f"/auctions/{created['id']}/bids",
        json={"amount": "100.00"},
        headers=first["headers"],
    )
    client.post(
        f"/auctions/{created['id']}/bids",
        json={"amount": "110.00"},
        headers=second["headers"],
    )

    notifications = client.get("/notifications", headers=first["headers"]).json()
    assert any(n["type"] == "outbid" for n in notifications)


def test_watch_and_unwatch(client, auction, make_user):
    created = auction()
    watcher = make_user()

    assert (
        client.post(f"/auctions/{created['id']}/watch", headers=watcher["headers"]).status_code
        == 204
    )
    assert client.get(f"/auctions/{created['id']}").json()["watchers"] == 1

    assert (
        client.delete(f"/auctions/{created['id']}/watch", headers=watcher["headers"]).status_code
        == 204
    )
    assert client.get(f"/auctions/{created['id']}").json()["watchers"] == 0


def test_only_seller_can_edit(client, auction, make_user):
    created = auction()
    other = make_user()
    response = client.patch(
        f"/auctions/{created['id']}",
        json={"title": "hijacked"},
        headers=other["headers"],
    )
    assert response.status_code == 403


def test_cancel_auction(client, auction):
    created = auction()
    response = client.post(f"/auctions/{created['id']}/cancel", headers=auction.seller["headers"])
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


def test_list_filters_by_status_and_category(client, auction):
    auction(category="art")
    response = client.get("/auctions", params={"category": "art", "status": "active"})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1
    assert all(item["category"] == "art" for item in body["items"])
