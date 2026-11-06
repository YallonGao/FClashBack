from __future__ import annotations

import base64
import http.server
import threading

import pytest

TITLE = "演示机场"
USERINFO = "upload=1073741824; download=2147483648; total=107374182400; expire=1893456000"


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        self.send_response(200)
        self.send_header("subscription-userinfo", USERINFO)
        self.send_header(
            "profile-title",
            "base64:" + base64.b64encode(TITLE.encode()).decode(),
        )
        self.send_header("profile-web-page-url", "https://airport.example.com")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture
def airport():
    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/link"
    finally:
        server.shutdown()


def test_preview_fills_name_site_and_usage(client, account, airport):
    response = client.post(
        "/api/v1/subscriptions/preview",
        json={"url": airport},
        headers=account["headers"],
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == TITLE
    assert body["site_url"] == "https://airport.example.com"
    assert body["traffic_used"] == 3221225472
    assert body["traffic_total"] == 107374182400
    assert body["expire_at"].startswith("2030-01-01")


def test_preview_rejects_a_bad_url(client, account):
    response = client.post(
        "/api/v1/subscriptions/preview",
        json={"url": "not a url"},
        headers=account["headers"],
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "invalid_url"


def test_preview_needs_authentication(client, airport):
    assert (
        client.post("/api/v1/subscriptions/preview", json={"url": airport}).status_code
        == 401
    )
