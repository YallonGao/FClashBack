from __future__ import annotations


def _create(client, headers, **overrides):
    payload = {
        "name": "Airport A",
        "url": "https://sub.example.com/link?token=abc",
        "site_url": "https://example.com",
        "account": "buyer@example.com",
        "password": "airport-secret",
        "note": "monthly",
        "enabled": True,
        "traffic_used": 10,
        "traffic_total": 100,
    }
    payload.update(overrides)
    return client.post("/api/v1/subscriptions", json=payload, headers=headers)


def test_create_and_list(client, account):
    created = _create(client, account["headers"])
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["name"] == "Airport A"
    assert body["account"] == "buyer@example.com"
    assert body["password"] == "airport-secret"
    assert body["traffic_total"] == 100

    listed = client.get("/api/v1/subscriptions", headers=account["headers"])
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [body["id"]]


def test_patch_updates_only_given_fields(client, account):
    created = _create(client, account["headers"]).json()

    patched = client.patch(
        f"/api/v1/subscriptions/{created['id']}",
        json={"enabled": False, "note": "expired"},
        headers=account["headers"],
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["enabled"] is False
    assert body["note"] == "expired"
    assert body["name"] == created["name"]
    assert body["password"] == created["password"]


def test_delete_removes_row(client, account):
    created = _create(client, account["headers"]).json()

    deleted = client.delete(
        f"/api/v1/subscriptions/{created['id']}", headers=account["headers"]
    )
    assert deleted.status_code == 204

    listed = client.get("/api/v1/subscriptions", headers=account["headers"])
    assert listed.json() == []


def test_other_account_cannot_touch_it(client, account):
    created = _create(client, account["headers"]).json()

    import uuid

    other = client.post(
        "/api/v1/auth/register",
        json={
            "username": f"other_{uuid.uuid4().hex[:10]}",
            "password": "correct horse battery",
            "device": {
                "key": "device-" + uuid.uuid4().hex,
                "name": "other",
                "platform": "linux",
            },
        },
    ).json()
    headers = {"Authorization": f"Bearer {other['tokens']['access_token']}"}

    assert client.get("/api/v1/subscriptions", headers=headers).json() == []
    assert (
        client.patch(
            f"/api/v1/subscriptions/{created['id']}",
            json={"name": "stolen"},
            headers=headers,
        ).status_code
        == 404
    )
    assert (
        client.delete(
            f"/api/v1/subscriptions/{created['id']}", headers=headers
        ).status_code
        == 404
    )


def test_requires_auth(client):
    assert client.get("/api/v1/subscriptions").status_code == 401
