"""Hardening checks: XSS, SQL injection, payload limits, headers.

These are integration tests because sanitisation happens at the DTO boundary
and is verified through the real endpoints.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

pytestmark = pytest.mark.integration


def _window() -> dict[str, str]:
    now = datetime.now(UTC)
    return {
        "start_time": (now - timedelta(seconds=1)).isoformat(),
        "end_time": (now + timedelta(minutes=10)).isoformat(),
    }


# --------------------------------------------------------------------------- #
# XSS
# --------------------------------------------------------------------------- #
def test_script_tags_are_stripped_from_title(client, make_user):
    seller = make_user()
    response = client.post(
        "/auctions",
        json={
            "title": "<script>alert(1)</script>Vintage watch",
            "starting_price": "10.00",
            "min_increment": "1.00",
            **_window(),
        },
        headers=seller["headers"],
    )
    assert response.status_code == 201
    title = response.json()["title"]
    assert "<script" not in title.lower()
    assert title == "alert(1)Vintage watch"


def test_event_handler_markup_is_removed(client, make_user):
    seller = make_user()
    response = client.post(
        "/auctions",
        json={
            "title": "Lamp",
            "description": '<img src=x onerror="alert(1)">Brass lamp',
            "starting_price": "10.00",
            "min_increment": "1.00",
            **_window(),
        },
        headers=seller["headers"],
    )
    assert response.status_code == 201
    description = response.json()["description"]
    assert "<img" not in description.lower()
    assert "onerror" not in description.lower()
    assert "Brass lamp" in description


def test_javascript_image_url_rejected(client, make_user):
    seller = make_user()
    response = client.post(
        "/auctions",
        json={
            "title": "Bad image",
            "image_url": "javascript:alert(1)",
            "starting_price": "10.00",
            "min_increment": "1.00",
            **_window(),
        },
        headers=seller["headers"],
    )
    assert response.status_code == 422


def test_data_uri_image_rejected(client, make_user):
    seller = make_user()
    response = client.post(
        "/auctions",
        json={
            "title": "Bad image",
            "image_url": "data:text/html;base64,PHNjcmlwdD4=",
            "starting_price": "10.00",
            "min_increment": "1.00",
            **_window(),
        },
        headers=seller["headers"],
    )
    assert response.status_code == 422


def test_username_rejects_markup(client):
    response = client.post(
        "/auth/register",
        json={
            "email": "xss@example.com",
            "username": "<script>alert(1)</script>",
            "password": "Passw0rd!123",
        },
    )
    assert response.status_code == 422


def test_control_characters_are_stripped(client, make_user):
    seller = make_user()
    response = client.post(
        "/auctions",
        json={
            "title": "Clock\x00\x07work",
            "starting_price": "10.00",
            "min_increment": "1.00",
            **_window(),
        },
        headers=seller["headers"],
    )
    assert response.status_code == 201
    assert "\x00" not in response.json()["title"]


# --------------------------------------------------------------------------- #
# SQL injection
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "payload",
    [
        "' OR 1=1 --",
        "'; DROP TABLE auctions; --",
        "%' UNION SELECT * FROM users --",
        "1; DELETE FROM bids",
    ],
)
def test_search_terms_are_treated_as_data(client, auction, payload):
    auction(title="Safe lot")
    response = client.get("/auctions", params={"q": payload})
    assert response.status_code == 200
    body = response.json()
    # Nothing matches, and crucially the tables still exist afterwards.
    assert body["total"] == 0
    assert client.get("/auctions").status_code == 200


def test_like_wildcards_are_escaped(client, auction):
    token = uuid.uuid4().hex[:8]
    # If "%" were treated as a wildcard, "1000 wool ..." would match too.
    auction(title=f"1000 wool {token}")
    auction(title=f"100% wool {token}")

    response = client.get("/auctions", params={"q": f"100% wool {token}"})
    assert response.status_code == 200
    titles = [item["title"] for item in response.json()["items"]]
    assert titles == [f"100% wool {token}"]


def test_email_lookup_is_parameterised(client):
    # A quote in the local part must not break the query.
    response = client.post(
        "/auth/login",
        json={"email": "o'brien@example.com", "password": "whatever"},
    )
    assert response.status_code == 401


# --------------------------------------------------------------------------- #
# transport hardening
# --------------------------------------------------------------------------- #
def test_security_headers_present(client):
    response = client.get("/")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert response.headers["Referrer-Policy"] == "no-referrer"


def test_oversized_body_rejected(client):
    big = "x" * (1024 * 1024 + 10)
    response = client.post(
        "/auth/register",
        json={"email": "big@example.com", "username": "biguser", "password": big},
    )
    assert response.status_code == 413


def test_invalid_content_length_rejected(client):
    response = client.post(
        "/auth/login",
        content=b"{}",
        headers={"Content-Length": "not-a-number", "Content-Type": "application/json"},
    )
    assert response.status_code in (400, 411, 422)


def test_error_responses_do_not_leak_internals(client):
    response = client.get("/auctions/not-a-uuid")
    assert response.status_code == 422
    body = response.text.lower()
    assert "traceback" not in body
    assert "psycopg" not in body
    assert "sqlalchemy" not in body
