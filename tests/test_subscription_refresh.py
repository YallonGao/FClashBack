from __future__ import annotations

import http.server
import threading

import pytest
from app.subscription_fetch import FetchError, fetch_usage, parse_userinfo

USERINFO = "upload=1048576; download=2097152; total=107374182400; expire=1893456000"


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler API)
        self.send_response(200)
        self.send_header("subscription-userinfo", USERINFO)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture
def subscription_server():
    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/link?token=abc"
    finally:
        server.shutdown()


def test_parse_userinfo_reads_every_field():
    usage = parse_userinfo(USERINFO)
    assert usage.upload == 1048576
    assert usage.download == 2097152
    assert usage.used == 3145728
    assert usage.total == 107374182400
    assert usage.expire_at is not None
    assert usage.expire_at.year == 2030


def test_parse_userinfo_rejects_missing_header():
    with pytest.raises(FetchError) as error:
        parse_userinfo(None)
    assert error.value.code == "no_userinfo"


def test_private_targets_are_refused_by_default():
    with pytest.raises(FetchError) as error:
        fetch_usage("http://127.0.0.1:8080/sub")
    assert error.value.code == "blocked_address"


def test_refresh_endpoint_updates_the_ledger(client, account, subscription_server):
    created = client.post(
        "/api/v1/subscriptions",
        json={"name": "Refreshable", "url": subscription_server},
        headers=account["headers"],
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["traffic_used"] == 0

    refreshed = client.post(
        f"/api/v1/subscriptions/{body['id']}/refresh", headers=account["headers"]
    )
    assert refreshed.status_code == 200, refreshed.text
    updated = refreshed.json()
    assert updated["traffic_used"] == 3145728
    assert updated["traffic_total"] == 107374182400
    assert updated["expire_at"].startswith("2030-01-01")


def test_refresh_without_url_is_rejected(client, account):
    created = client.post(
        "/api/v1/subscriptions",
        json={"name": "No url"},
        headers=account["headers"],
    ).json()
    response = client.post(
        f"/api/v1/subscriptions/{created['id']}/refresh", headers=account["headers"]
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "no_url"
