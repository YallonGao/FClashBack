from __future__ import annotations

import base64
import uuid


def _upload(item_id: str, *, kind: str = "profile", title: str = "Airport", content: str = "x"):
    return {
        "kind": kind,
        "item_id": item_id,
        "title": title,
        "content": base64.b64encode(content.encode()).decode(),
    }


def _sync(client, headers, since=0, uploads=(), holdings=None):
    response = client.post(
        "/api/v1/cloud/sync",
        json={"since": since, "uploads": list(uploads), "holdings": holdings or {}},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _items(client, headers):
    response = client.get("/api/v1/cloud/items", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_upload_shows_up_with_its_uploader(client, account):
    result = _sync(client, account["headers"], uploads=[_upload("p1")])
    assert [item["item_id"] for item in result["items"]] == ["p1"]

    listed = _items(client, account["headers"])
    assert listed[0]["uploader_name"] == "test"
    assert listed[0]["title"] == "Airport"


def test_identical_upload_does_not_move_the_revision(client, account):
    first = _sync(client, account["headers"], uploads=[_upload("p1")])
    again = _sync(
        client, account["headers"], since=first["revision"], uploads=[_upload("p1")]
    )
    assert again["revision"] == first["revision"]
    assert again["items"] == []


def test_holdings_are_replaced_for_the_kind_reported(client, account):
    _sync(client, account["headers"], uploads=[_upload("p1"), _upload("p2")])
    _sync(client, account["headers"], holdings={"profile": ["p1", "p2"]})
    assert {item["item_id"]: len(item["holders"]) for item in _items(client, account["headers"])} == {
        "p1": 1,
        "p2": 1,
    }

    _sync(client, account["headers"], holdings={"profile": ["p1"]})
    assert {item["item_id"]: len(item["holders"]) for item in _items(client, account["headers"])} == {
        "p1": 1,
        "p2": 0,
    }


def test_a_kind_the_device_does_not_mention_keeps_its_holdings(client, account):
    _sync(client, account["headers"], uploads=[_upload("p1")])
    _sync(client, account["headers"], holdings={"profile": ["p1"]})

    # An older client that knows nothing about scripts must not lose the
    # profile holding it just reported.
    _sync(client, account["headers"], holdings={"script": []})

    listed = _items(client, account["headers"])
    assert len(listed[0]["holders"]) == 1





def test_deleting_from_the_catalogue_leaves_a_tombstone(client, account):
    first = _sync(client, account["headers"], uploads=[_upload("p1")])

    removed = client.delete("/api/v1/cloud/items/profile/p1", headers=account["headers"])
    assert removed.status_code == 204

    after = _sync(client, account["headers"], since=first["revision"])
    assert after["tombstones"] == [{"kind": "profile", "item_id": "p1"}]
    assert _items(client, account["headers"]) == []



def test_another_account_sees_nothing(client, account):
    _sync(client, account["headers"], uploads=[_upload("p1")])
    other = client.post(
        "/api/v1/auth/register",
        json={
            "username": f"cloud_{uuid.uuid4().hex[:10]}",
            "password": "correct horse battery",
            "device": {"key": "device-" + uuid.uuid4().hex, "name": "other", "platform": "web"},
        },
    ).json()
    headers = {"Authorization": f"Bearer {other['tokens']['access_token']}"}
    assert _items(client, headers) == []


def test_cloud_requires_authentication(client):
    assert client.get("/api/v1/cloud/items").status_code == 401


def test_two_hashes_answer_two_different_questions(client, account):
    first = _sync(
        client, account["headers"], uploads=[_upload("p1", title="Airport A", content="body")]
    )
    item = first["items"][0]
    assert item["content_hash"] != item["checksum"]

    # Renaming is a change worth uploading, but the payload did not move.
    renamed = _sync(
        client,
        account["headers"],
        since=first["revision"],
        uploads=[_upload("p1", title="Airport B", content="body")],
    )
    assert renamed["items"][0]["content_hash"] == item["content_hash"]
    assert renamed["items"][0]["checksum"] != item["checksum"]

    # An airport refresh changes the payload without anyone renaming anything.
    refreshed = _sync(
        client,
        account["headers"],
        since=renamed["revision"],
        uploads=[_upload("p1", title="Airport B", content="body v2")],
    )
    assert refreshed["items"][0]["content_hash"] != item["content_hash"]


def _upload_based(item_id: str, base: str, *, title="Airport", content="x"):
    payload = _upload(item_id, title=title, content=content)
    payload["base_checksum"] = base
    return payload


def test_stale_base_is_a_conflict_not_an_overwrite(client, account):
    first = _sync(client, account["headers"], uploads=[_upload("p1", content="v1")])
    checksum = first["items"][0]["checksum"]

    stale = _sync(
        client,
        account["headers"],
        since=first["revision"],
        uploads=[_upload_based("p1", "0" * 64, content="v2")],
    )
    assert len(stale["conflicts"]) == 1
    assert stale["conflicts"][0]["item_id"] == "p1"
    # The cloud copy must not move.
    assert stale["items"] == []

    current = _sync(client, account["headers"], since=0)
    assert current["items"][0]["checksum"] == checksum


def test_conflict_can_be_resolved_towards_the_upload(client, account):
    first = _sync(client, account["headers"], uploads=[_upload("p1", content="v1")])
    _sync(
        client,
        account["headers"],
        since=first["revision"],
        uploads=[_upload_based("p1", "0" * 64, title="Device", content="v2")],
    )

    resolved = client.post(
        "/api/v1/cloud/conflicts/profile/p1/resolve",
        json={"keep": "uploaded"},
        headers=account["headers"],
    )
    assert resolved.status_code == 204

    after = _sync(client, account["headers"], since=0)
    assert after["conflicts"] == []
    assert after["items"][0]["title"] == "Device"


def test_conflict_can_be_resolved_towards_the_cloud(client, account):
    first = _sync(client, account["headers"], uploads=[_upload("p1", content="v1")])
    before = first["items"][0]["checksum"]
    _sync(
        client,
        account["headers"],
        since=first["revision"],
        uploads=[_upload_based("p1", "0" * 64, content="v2")],
    )

    resolved = client.post(
        "/api/v1/cloud/conflicts/profile/p1/resolve",
        json={"keep": "cloud"},
        headers=account["headers"],
    )
    assert resolved.status_code == 204

    after = _sync(client, account["headers"], since=0)
    assert after["conflicts"] == []
    assert after["items"][0]["checksum"] == before


def test_editing_something_the_cloud_deleted_is_a_conflict(client, account):
    first = _sync(client, account["headers"], uploads=[_upload("p1", content="v1")])
    client.delete("/api/v1/cloud/items/profile/p1", headers=account["headers"])

    pushed = _sync(
        client,
        account["headers"],
        since=first["revision"] + 1,
        uploads=[_upload_based("p1", first["items"][0]["checksum"], content="v2")],
    )
    assert pushed["conflicts"][0]["cloud_deleted"] is True
    assert [item["item_id"] for item in pushed["items"]] == []

    # Keeping the upload brings the item back, which is the whole point of
    # letting a person decide.
    client.post(
        "/api/v1/cloud/conflicts/profile/p1/resolve",
        json={"keep": "uploaded"},
        headers=account["headers"],
    )
    assert [item["item_id"] for item in _items(client, account["headers"])] == ["p1"]


def _second_device(client, account):
    """Log the same account in from another device and return its headers."""
    response = client.post(
        "/api/v1/auth/login",
        json={
            "username": account["username"],
            "password": account["password"],
            "device": {"key": "device-second-01", "name": "second", "platform": "web"},
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return {"Authorization": f"Bearer {body['tokens']['access_token']}"}, body["device"]["id"]


def test_a_second_device_conflict_replaces_the_first_one(client, account):
    """Documents a known limit: one conflict slot per item.

    Both devices must be stale for a conflict, so each upload below is based
    on C1 while the cloud has moved to C2. The second device's conflict takes
    the slot; the first device's copy still exists on that device, only the
    console view keeps one. Per-device conflicts need a schema change.
    """
    first = _sync(client, account["headers"], uploads=[_upload("p1", content="v1")])
    c1 = first["items"][0]["checksum"]

    second_headers, second_device = _second_device(client, account)

    # B moves the cloud to C2, so both later uploads are based on a dead version.
    moved = _sync(
        client,
        second_headers,
        since=first["revision"],
        uploads=[_upload_based("p1", c1, title="From B", content="v2")],
    )
    assert moved["conflicts"] == []
    c2 = [item for item in moved["items"] if item["item_id"] == "p1"][0]["checksum"]
    assert c2 != c1

    a = _sync(
        client,
        account["headers"],
        since=moved["revision"],
        uploads=[_upload_based("p1", c1, title="From A", content="v3")],
    )
    assert [row["device_title"] for row in a["conflicts"]] == ["From A"]

    b = _sync(
        client,
        second_headers,
        since=moved["revision"],
        uploads=[_upload_based("p1", c1, title="From B again", content="v4")],
    )
    assert len(b["conflicts"]) == 1, b["conflicts"]
    assert b["conflicts"][0]["device_title"] == "From B again"
    assert b["conflicts"][0]["device_id"] == second_device
