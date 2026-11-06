from __future__ import annotations

import base64

import pytest


def _payload(profile_id: str, label: str = "Airport", content: str = "proxies: []"):
    return {
        "profile_id": profile_id,
        "label": label,
        "url": "https://sub.example.com/link",
        "type": "url",
        "content": base64.b64encode(content.encode()).decode(),
        "sort_order": 0,
    }


def _push(client, headers, since=0, upserts=(), deletes=()):
    response = client.post(
        "/api/v1/sync/profiles",
        json={"since": since, "upserts": list(upserts), "deletes": list(deletes)},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _pull(client, headers, since=0):
    response = client.get(
        f"/api/v1/sync/profiles?since={since}", headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_first_push_publishes_every_profile(client, account):
    result = _push(client, account["headers"], upserts=[_payload("1"), _payload("2")])
    assert {item["profile_id"] for item in result["upserts"]} == {"1", "2"}
    assert result["tombstones"] == []
    assert result["revision"] == 2


def test_second_device_sees_only_what_changed(client, account):
    first = _push(client, account["headers"], upserts=[_payload("1")])
    second = _push(
        client, account["headers"], since=first["revision"], upserts=[_payload("2")]
    )
    assert [item["profile_id"] for item in second["upserts"]] == ["2"]


def test_delete_leaves_a_tombstone_for_other_devices(client, account):
    first = _push(client, account["headers"], upserts=[_payload("1"), _payload("2")])
    removed = _push(
        client, account["headers"], since=first["revision"], deletes=["2"]
    )
    assert removed["tombstones"] == ["2"]
    assert removed["upserts"] == []

    later = _pull(client, account["headers"], since=first["revision"])
    assert later["tombstones"] == ["2"]


def test_identical_push_does_not_move_the_revision(client, account):
    first = _push(client, account["headers"], upserts=[_payload("1")])
    again = _push(
        client, account["headers"], since=first["revision"], upserts=[_payload("1")]
    )
    assert again["revision"] == first["revision"]
    assert again["upserts"] == []


def test_recreating_a_deleted_profile_wins(client, account):
    first = _push(client, account["headers"], upserts=[_payload("1")])
    _push(client, account["headers"], deletes=["1"])
    back = _push(
        client,
        account["headers"],
        since=first["revision"],
        upserts=[_payload("1", label="Reborn")],
    )
    assert back["tombstones"] == []
    assert [item["label"] for item in back["upserts"]] == ["Reborn"]


def test_content_change_is_published(client, account):
    first = _push(client, account["headers"], upserts=[_payload("1", content="a: 1")])
    changed = _push(
        client,
        account["headers"],
        since=first["revision"],
        upserts=[_payload("1", content="a: 2")],
    )
    assert changed["revision"] == first["revision"] + 1
    assert changed["upserts"][0]["content"] == base64.b64encode(b"a: 2").decode()


def test_two_accounts_do_not_mix(client, account):
    _push(client, account["headers"], upserts=[_payload("1")])

    import uuid

    other = client.post(
        "/api/v1/auth/register",
        json={
            "username": f"other_{uuid.uuid4().hex[:10]}",
            "password": "correct horse battery",
            "device": {"key": "device-" + uuid.uuid4().hex, "name": "o", "platform": "web"},
        },
    ).json()
    headers = {"Authorization": f"Bearer {other['tokens']['access_token']}"}
    assert _pull(client, headers)["upserts"] == []


def test_sync_requires_authentication(client):
    assert client.get("/api/v1/sync/profiles").status_code == 401


@pytest.mark.parametrize("since", [0, 5])
def test_pull_is_paged_by_revision(client, account, since):
    _push(client, account["headers"], upserts=[_payload("1")])
    result = _pull(client, account["headers"], since=since)
    assert result["revision"] >= 1
