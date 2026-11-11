"""Admin-only behaviour."""

from __future__ import annotations

import asyncio

import pytest
from src.common.constants.enums import UserRole
from src.database.session import SessionLocal
from src.modules.users.repositories.user_repository import UserRepository

pytestmark = pytest.mark.integration


def _promote(user_id: str) -> None:
    async def run() -> None:
        from uuid import UUID

        async with SessionLocal() as session:
            repo = UserRepository(session)
            user = await repo.get_by_id(UUID(user_id))
            assert user is not None
            await repo.set_role(user, UserRole.admin)
            await repo.commit()

    asyncio.run(run())


@pytest.fixture
def admin(client, make_user):
    user = make_user()
    _promote(user["id"])
    return user


def test_admin_can_list_users(client, admin):
    response = client.get("/admin/users", headers=admin["headers"])
    assert response.status_code == 200
    assert isinstance(response.json()["data"], list)


def test_normal_user_cannot_reach_admin(client, make_user):
    user = make_user()
    assert client.get("/admin/stats", headers=user["headers"]).status_code == 403
    assert client.get("/admin/users", headers=user["headers"]).status_code == 403


def test_admin_can_promote_another_user(client, admin, make_user):
    target = make_user()
    response = client.patch(
        f"/admin/users/{target['id']}/role",
        json={"role": "admin"},
        headers=admin["headers"],
    )
    assert response.status_code == 200
    assert response.json()["data"]["role"] == "admin"


def test_admin_cannot_change_own_role(client, admin):
    response = client.patch(
        f"/admin/users/{admin['id']}/role",
        json={"role": "user"},
        headers=admin["headers"],
    )
    assert response.status_code == 409


def test_admin_cannot_disable_self(client, admin):
    response = client.patch(
        f"/admin/users/{admin['id']}/active",
        params={"is_active": "false"},
        headers=admin["headers"],
    )
    assert response.status_code == 409


def test_admin_can_force_end_auction(client, admin, auction):
    created = auction()
    response = client.post(f"/admin/auctions/{created['id']}/end", headers=admin["headers"])
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "ended"


def test_admin_stats_shape(client, admin):
    response = client.get("/admin/stats", headers=admin["headers"])
    assert response.status_code == 200
    assert {"users", "auctions", "bids", "active_auctions"} <= response.json()["data"].keys()
