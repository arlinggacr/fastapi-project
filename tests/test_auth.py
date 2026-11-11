"""Authentication behaviour."""

from __future__ import annotations

import pytest
from tests.conftest import _suffix

pytestmark = pytest.mark.integration


def test_register_login_and_me(client, make_user):
    user = make_user()
    response = client.get("/users/me", headers=user["headers"])
    assert response.status_code == 200
    assert response.json()["data"]["username"] == user["username"]
    assert response.json()["data"]["role"] == "user"


def test_duplicate_email_rejected(client, make_user):
    user = make_user()
    response = client.post(
        "/auth/register",
        json={
            "email": user["email"],
            "username": f"other{_suffix()}",
            "password": "Passw0rd!123",
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EMAIL_TAKEN"


def test_wrong_password_rejected(client, make_user):
    user = make_user()
    response = client.post("/auth/login", json={"email": user["email"], "password": "nope"})
    assert response.status_code == 401


def test_refresh_issues_new_access_token(client, make_user):
    user = make_user()
    response = client.post("/auth/refresh", json={"refresh_token": user["refresh"]})
    assert response.status_code == 200
    new_access = response.json()["data"]["access_token"]
    assert (
        client.get("/users/me", headers={"Authorization": f"Bearer {new_access}"}).status_code
        == 200
    )


def test_access_token_cannot_be_used_as_refresh(client, make_user):
    user = make_user()
    response = client.post("/auth/refresh", json={"refresh_token": user["token"]})
    assert response.status_code == 401


def test_password_change(client, make_user):
    user = make_user()
    response = client.post(
        "/auth/me/password",
        json={"current_password": user["password"], "new_password": "N3wPassw0rd!"},
        headers=user["headers"],
    )
    assert response.status_code == 204
    assert (
        client.post(
            "/auth/login", json={"email": user["email"], "password": "N3wPassw0rd!"}
        ).status_code
        == 200
    )


def test_protected_route_requires_token(client):
    assert client.get("/users/me").status_code == 401


def test_admin_route_forbidden_for_normal_user(client, make_user):
    user = make_user()
    assert client.get("/admin/users", headers=user["headers"]).status_code == 403
