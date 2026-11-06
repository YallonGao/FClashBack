from __future__ import annotations


def _push(client, headers, payload: bytes, base: int):
    return client.put(
        f"/api/v1/sync/snapshot?base_revision={base}",
        content=payload,
        headers={**headers, "Content-Type": "application/octet-stream"},
    )


def test_state_starts_empty(client, account):
    state = client.get("/api/v1/sync/state", headers=account["headers"]).json()
    assert state == {
        "revision": 0,
        "checksum": "",
        "size": 0,
        "updated_at": None,
        "device_id": None,
    }


def test_push_then_pull_roundtrip(client, account):
    payload = b"profiles:\n  - id: 1\n"
    pushed = _push(client, account["headers"], payload, 0)
    assert pushed.status_code == 200, pushed.text
    assert pushed.json()["revision"] == 1

    state = client.get("/api/v1/sync/state", headers=account["headers"]).json()
    assert state["revision"] == 1
    assert state["size"] == len(payload)

    pulled = client.get("/api/v1/sync/snapshot", headers=account["headers"])
    assert pulled.status_code == 200
    assert pulled.content == payload
    assert pulled.headers["X-Revision"] == "1"


def test_stale_base_revision_is_rejected(client, account):
    assert _push(client, account["headers"], b"v1", 0).status_code == 200
    conflict = _push(client, account["headers"], b"v2", 0)
    assert conflict.status_code == 409
    detail = conflict.json()["detail"]
    assert detail["detail"] == "revision_conflict"
    assert detail["current_revision"] == 1


def test_second_device_must_pull_before_pushing(client, account):
    first = _push(client, account["headers"], b"from-device-a", 0)
    assert first.status_code == 200

    login = client.post(
        "/api/v1/auth/login",
        json={
            "username": account["username"],
            "password": account["password"],
            "device": {"key": "device-b-" + account["username"], "name": "PC", "platform": "windows"},
        },
    ).json()
    headers_b = {"Authorization": f"Bearer {login['tokens']['access_token']}"}

    assert _push(client, headers_b, b"from-device-b", 0).status_code == 409
    assert _push(client, headers_b, b"from-device-b", 1).status_code == 200
    assert client.get("/api/v1/sync/snapshot", headers=headers_b).content == b"from-device-b"


def test_empty_snapshot_is_rejected(client, account):
    assert _push(client, account["headers"], b"", 0).status_code == 400


def test_history_keeps_previous_revisions(client, account):
    for index in range(3):
        assert _push(client, account["headers"], f"v{index}".encode(), index).status_code == 200
    history = client.get("/api/v1/sync/history", headers=account["headers"]).json()
    assert [item["revision"] for item in history] == [3, 2, 1]

    old = client.get("/api/v1/sync/history/1", headers=account["headers"])
    assert old.content == b"v0"


def test_restore_creates_a_new_revision(client, account):
    assert _push(client, account["headers"], b"keep-me", 0).status_code == 200
    assert _push(client, account["headers"], b"broken", 1).status_code == 200

    restored = client.post(
        "/api/v1/sync/restore/1?base_revision=2", headers=account["headers"]
    )
    assert restored.status_code == 200
    assert restored.json()["revision"] == 3
    assert client.get("/api/v1/sync/snapshot", headers=account["headers"]).content == b"keep-me"


def test_history_is_pruned_to_the_configured_limit(client, account):
    for index in range(8):
        assert _push(client, account["headers"], f"v{index}".encode(), index).status_code == 200
    history = client.get(
        "/api/v1/sync/history?limit=100", headers=account["headers"]
    ).json()
    assert len(history) == 5
    assert history[0]["revision"] == 8


def test_snapshots_are_isolated_between_accounts(client, account):
    assert _push(client, account["headers"], b"mine", 0).status_code == 200

    import uuid

    other = client.post(
        "/api/v1/auth/register",
        json={
            "username": f"bob_{uuid.uuid4().hex[:8]}",
            "password": "hunter2hunter2",
            "device": {"key": "device-" + uuid.uuid4().hex, "name": "x", "platform": "linux"},
        },
    ).json()
    headers = {"Authorization": f"Bearer {other['tokens']['access_token']}"}
    assert client.get("/api/v1/sync/snapshot", headers=headers).status_code == 404
    assert client.get("/api/v1/sync/state", headers=headers).json()["revision"] == 0
