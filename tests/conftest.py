from __future__ import annotations

import os
import tempfile

import pytest

_TMP = tempfile.mkdtemp(prefix="fclash-test-")
os.environ["FCLASH_DATA_DIR"] = _TMP
os.environ["FCLASH_DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["FCLASH_JWT_SECRET"] = "test-secret-0123456789abcdef0123456789"
os.environ["FCLASH_HISTORY_LIMIT"] = "5"
os.environ["FCLASH_ALLOW_PRIVATE_FETCH"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def account(client):
    import uuid

    username = f"user_{uuid.uuid4().hex[:12]}"
    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "password": "correct horse battery",
            "device": {"key": "device-" + uuid.uuid4().hex, "name": "test", "platform": "linux"},
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return {
        "username": username,
        "password": "correct horse battery",
        "token": body["tokens"]["access_token"],
        "refresh": body["tokens"]["refresh_token"],
        "device_id": body["device"]["id"],
        "headers": {"Authorization": f"Bearer {body['tokens']['access_token']}"},
    }
