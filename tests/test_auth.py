from __future__ import annotations

import uuid


def _device(key: str | None = None) -> dict[str, str]:
    return {
        "key": key or "device-" + uuid.uuid4().hex,
        "name": "Pixel",
        "platform": "android",
    }


def test_register_returns_session_and_token_works(client):
    username = f"alice_{uuid.uuid4().hex[:8]}"
    response = client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": "hunter2hunter2", "device": _device()},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["user"]["username"] == username
    assert body["tokens"]["token_type"] == "bearer"

    me = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {body['tokens']['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["username"] == username


def test_duplicate_username_is_rejected(client, account):
    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": account["username"],
            "password": "another-password",
            "device": _device(),
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "username_taken"


def test_login_with_wrong_password_is_rejected(client, account):
    response = client.post(
        "/api/v1/auth/login",
        json={
            "username": account["username"],
            "password": "not-the-password",
            "device": _device(),
        },
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "invalid_credentials"


def test_login_reuses_the_same_device_row(client, account):
    key = "device-" + uuid.uuid4().hex
    first = client.post(
        "/api/v1/auth/login",
        json={"username": account["username"], "password": account["password"], "device": _device(key)},
    )
    second = client.post(
        "/api/v1/auth/login",
        json={"username": account["username"], "password": account["password"], "device": _device(key)},
    )
    assert first.json()["device"]["id"] == second.json()["device"]["id"]


def test_refresh_issues_a_new_access_token(client, account):
    response = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": account["refresh"]}
    )
    assert response.status_code == 200
    token = response.json()["access_token"]
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200


def test_access_token_is_not_accepted_as_refresh_token(client, account):
    response = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": account["token"]}
    )
    assert response.status_code == 401


def test_missing_token_is_unauthorized(client):
    assert client.get("/api/v1/sync/state").status_code == 401


def test_revoked_device_loses_access(client, account):
    other = client.post(
        "/api/v1/auth/login",
        json={
            "username": account["username"],
            "password": account["password"],
            "device": _device(),
        },
    ).json()
    revoke = client.delete(
        f"/api/v1/devices/{other['device']['id']}", headers=account["headers"]
    )
    assert revoke.status_code == 204

    denied = client.get(
        "/api/v1/sync/state",
        headers={"Authorization": f"Bearer {other['tokens']['access_token']}"},
    )
    assert denied.status_code == 401
    assert denied.json()["detail"] == "session_revoked"


def test_cannot_revoke_the_device_making_the_request(client, account):
    response = client.delete(
        f"/api/v1/devices/{account['device_id']}", headers=account["headers"]
    )
    assert response.status_code == 400
