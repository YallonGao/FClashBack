from __future__ import annotations


def test_password_change_requires_the_current_one(client, account):
    response = client.post(
        "/api/v1/auth/password",
        json={"current_password": "wrong", "new_password": "another-secret-1"},
        headers=account["headers"],
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "wrong_password"


def test_password_change_then_login_with_the_new_one(client, account):
    changed = client.post(
        "/api/v1/auth/password",
        json={
            "current_password": account["password"],
            "new_password": "brand-new-secret",
        },
        headers=account["headers"],
    )
    assert changed.status_code == 204

    stale = client.post(
        "/api/v1/auth/login",
        json={
            "username": account["username"],
            "password": account["password"],
            "device": {"key": "device-pw-0001", "name": "x", "platform": "web"},
        },
    )
    assert stale.status_code == 401

    fresh = client.post(
        "/api/v1/auth/login",
        json={
            "username": account["username"],
            "password": "brand-new-secret",
            "device": {"key": "device-pw-0002", "name": "x", "platform": "web"},
        },
    )
    assert fresh.status_code == 200


def test_password_change_needs_authentication(client):
    response = client.post(
        "/api/v1/auth/password",
        json={"current_password": "a", "new_password": "brand-new-secret"},
    )
    assert response.status_code == 401
