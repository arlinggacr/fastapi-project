"""Auction image upload behaviour.

Covers validation (which happens before any network call), ownership rules,
and the persisted key/url pair. Tests that need the real bucket are marked
``integration`` like the rest of the suite.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from src.modules.auctions.services.image_service import (
    MAX_FILES_PER_REQUEST,
    sniff_image_type,
)

pytestmark = pytest.mark.integration

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 60
GIF = b"GIF89a" + b"\x00" * 60
WEBP = b"RIFF" + (60).to_bytes(4, "little") + b"WEBP" + b"\x00" * 60


def _auction(client, make_user) -> tuple[str, dict]:
    seller = make_user("seller")
    now = datetime.now(UTC)
    response = client.post(
        "/auctions",
        json={
            "title": f"Image lot {uuid.uuid4().hex[:8]}",
            "description": "image test",
            "category": "test",
            "starting_price": "10.00",
            "min_increment": "1.00",
            "start_time": (now - timedelta(seconds=1)).isoformat(),
            "end_time": (now + timedelta(minutes=10)).isoformat(),
        },
        headers=seller["headers"],
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"], seller


# --------------------------------------------------------------------------- #
# magic-byte sniffing (no network)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (PNG, "image/png"),
        (JPEG, "image/jpeg"),
        (GIF, "image/gif"),
        (WEBP, "image/webp"),
        (b"MZ\x90\x00" + b"\x00" * 60, None),  # a Windows executable
        (b"<script>alert(1)</script>", None),
        (b"", None),
    ],
)
def test_sniff_image_type(payload, expected):
    assert sniff_image_type(payload[:16]) == expected


# --------------------------------------------------------------------------- #
# upload
# --------------------------------------------------------------------------- #
def test_single_upload_stores_key_and_url(client, make_user):
    auction_id, seller = _auction(client, make_user)
    response = client.post(
        f"/auctions/{auction_id}/images",
        files=[("files", ("one.png", PNG, "image/png"))],
        headers=seller["headers"],
    )

    assert response.status_code == 201, response.text
    images = response.json()["data"]
    assert len(images) == 1

    image = images[0]
    assert image["key"].startswith("auction/")
    assert image["key"].endswith(".png")
    assert image["url"].endswith(image["key"])
    assert image["content_type"] == "image/png"
    assert image["size_bytes"] == len(PNG)
    assert image["position"] == 0


def test_multiple_upload_preserves_order(client, make_user):
    auction_id, seller = _auction(client, make_user)
    response = client.post(
        f"/auctions/{auction_id}/images",
        files=[
            ("files", ("a.png", PNG, "image/png")),
            ("files", ("b.jpg", JPEG, "image/jpeg")),
            ("files", ("c.gif", GIF, "image/gif")),
        ],
        headers=seller["headers"],
    )

    assert response.status_code == 201, response.text
    images = response.json()["data"]
    assert [image["content_type"] for image in images] == [
        "image/png",
        "image/jpeg",
        "image/gif",
    ]
    assert [image["position"] for image in images] == [0, 1, 2]
    assert len({image["key"] for image in images}) == 3


def test_first_image_becomes_the_cover(client, make_user):
    auction_id, seller = _auction(client, make_user)
    upload = client.post(
        f"/auctions/{auction_id}/images",
        files=[("files", ("cover.png", PNG, "image/png"))],
        headers=seller["headers"],
    ).json()["data"][0]

    auction = client.get(f"/auctions/{auction_id}").json()["data"]
    assert auction["image_url"] == upload["url"]


def test_upload_is_listed(client, make_user):
    auction_id, seller = _auction(client, make_user)
    client.post(
        f"/auctions/{auction_id}/images",
        files=[("files", ("one.png", PNG, "image/png"))],
        headers=seller["headers"],
    )

    listed = client.get(f"/auctions/{auction_id}/images").json()["data"]
    assert len(listed) == 1
    assert listed[0]["key"].startswith("auction/")


# --------------------------------------------------------------------------- #
# validation and ownership
# --------------------------------------------------------------------------- #
def test_non_image_is_rejected(client, make_user):
    auction_id, seller = _auction(client, make_user)
    response = client.post(
        f"/auctions/{auction_id}/images",
        files=[("files", ("payload.png", b"MZ\x90\x00" + b"\x00" * 60, "image/png"))],
        headers=seller["headers"],
    )

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "UNSUPPORTED_IMAGE"


def test_empty_file_is_rejected(client, make_user):
    auction_id, seller = _auction(client, make_user)
    response = client.post(
        f"/auctions/{auction_id}/images",
        files=[("files", ("empty.png", b"", "image/png"))],
        headers=seller["headers"],
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "EMPTY_FILE"


def test_too_many_files_rejected(client, make_user):
    auction_id, seller = _auction(client, make_user)
    response = client.post(
        f"/auctions/{auction_id}/images",
        files=[
            ("files", (f"{index}.png", PNG, "image/png"))
            for index in range(MAX_FILES_PER_REQUEST + 1)
        ],
        headers=seller["headers"],
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "TOO_MANY_FILES"


def test_upload_requires_auth(client, make_user):
    auction_id, _ = _auction(client, make_user)
    response = client.post(
        f"/auctions/{auction_id}/images",
        files=[("files", ("one.png", PNG, "image/png"))],
    )
    assert response.status_code == 401


def test_only_seller_can_upload(client, make_user):
    auction_id, _ = _auction(client, make_user)
    other = make_user()
    response = client.post(
        f"/auctions/{auction_id}/images",
        files=[("files", ("one.png", PNG, "image/png"))],
        headers=other["headers"],
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_upload_to_unknown_auction_is_404(client, make_user):
    seller = make_user("seller")
    response = client.post(
        f"/auctions/{uuid.uuid4()}/images",
        files=[("files", ("one.png", PNG, "image/png"))],
        headers=seller["headers"],
    )
    assert response.status_code == 404


# --------------------------------------------------------------------------- #
# delete
# --------------------------------------------------------------------------- #
def test_delete_removes_image_and_clears_cover(client, make_user):
    auction_id, seller = _auction(client, make_user)
    image = client.post(
        f"/auctions/{auction_id}/images",
        files=[("files", ("one.png", PNG, "image/png"))],
        headers=seller["headers"],
    ).json()["data"][0]

    response = client.delete(
        f"/auctions/{auction_id}/images/{image['id']}", headers=seller["headers"]
    )
    assert response.status_code == 204

    assert client.get(f"/auctions/{auction_id}/images").json()["data"] == []
    assert client.get(f"/auctions/{auction_id}").json()["data"]["image_url"] is None


def test_only_seller_can_delete_image(client, make_user):
    auction_id, seller = _auction(client, make_user)
    image = client.post(
        f"/auctions/{auction_id}/images",
        files=[("files", ("one.png", PNG, "image/png"))],
        headers=seller["headers"],
    ).json()["data"][0]

    other = make_user()
    response = client.delete(
        f"/auctions/{auction_id}/images/{image['id']}", headers=other["headers"]
    )
    assert response.status_code == 403


def test_deleting_auction_removes_its_images(client, make_user):
    auction_id, seller = _auction(client, make_user)
    image = client.post(
        f"/auctions/{auction_id}/images",
        files=[("files", ("one.png", PNG, "image/png"))],
        headers=seller["headers"],
    ).json()["data"][0]

    # An active auction must be cancelled before it can be deleted.
    assert (
        client.post(f"/auctions/{auction_id}/cancel", headers=seller["headers"]).status_code
        == 200
    )
    assert (
        client.delete(f"/auctions/{auction_id}", headers=seller["headers"]).status_code == 204
    )
    assert client.get(f"/auctions/{auction_id}/images").status_code == 404

    # The rows cascade away with the auction, so the object must be purged
    # from the bucket too instead of being orphaned there.
    assert httpx.get(image["access_url"], timeout=30).status_code == 404
