"""Shared pytest fixtures.

These tests run against the real Neon + Upstash services configured in `.env`
(they create throwaway records prefixed with a random suffix).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from src.main import app
from starlette.testclient import TestClient

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def _suffix() -> str:
    return uuid.uuid4().hex[:12]


@pytest.fixture
def make_user(client: TestClient):
    created: list[dict] = []

    def _make(role: str = "user") -> dict:
        name = f"{role}{_suffix()}"
        body = {
            "email": f"{name}@example.com",
            "username": name,
            "password": "Passw0rd!123",
        }
        response = client.post("/auth/register", json=body)
        assert response.status_code == 201, response.text
        tokens = client.post(
            "/auth/login", json={"email": body["email"], "password": body["password"]}
        ).json()
        user = {
            **body,
            "id": response.json()["id"],
            "token": tokens["access_token"],
            "refresh": tokens["refresh_token"],
            "headers": {"Authorization": f"Bearer {tokens['access_token']}"},
        }
        created.append(user)
        return user

    _make.created = created
    return _make


@pytest.fixture
def auction(client: TestClient, make_user):
    seller = make_user("seller")

    def _create(**overrides) -> dict:
        now = datetime.now(UTC)
        payload = {
            "title": f"Lot {_suffix()}",
            "description": "test lot",
            "category": "test",
            "starting_price": "100.00",
            "min_increment": "10.00",
            "start_time": (now - timedelta(seconds=1)).isoformat(),
            "end_time": (now + timedelta(minutes=10)).isoformat(),
        }
        payload.update(overrides)
        response = client.post("/auctions", json=payload, headers=seller["headers"])
        assert response.status_code == 201, response.text
        return response.json()

    _create.seller = seller
    return _create
