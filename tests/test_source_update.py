"""PATCH /api/v1/sources/{source_id}: admins turn a source on or off."""

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from tests.pg_support import TEST_ADMIN_TOKEN

FEED = {"name": "Example AI News", "feed_url": "https://example.com/feed.xml"}


def create_source(client: TestClient) -> int:
    """Save a source through the API and return its id."""
    response = client.post("/api/v1/sources", json=FEED)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def patch(client: TestClient, source_id: int, body: dict, token: str | None):
    """Send the PATCH with the given admin token, or with none at all."""
    headers = {"X-Admin-Token": token} if token is not None else {}
    return client.patch(f"/api/v1/sources/{source_id}", json=body, headers=headers)


@pytest.fixture
def anonymous(client: TestClient) -> TestClient:
    """The shared client without its default admin header."""
    client.headers.pop("X-Admin-Token", None)
    return client


def test_missing_token_is_401(anonymous: TestClient) -> None:
    assert patch(anonymous, 1, {"is_active": False}, None).status_code == 401


def test_wrong_token_is_401(anonymous: TestClient) -> None:
    assert patch(anonymous, 1, {"is_active": False}, "wrong-token").status_code == 401


@pytest.mark.parametrize("configured", [None, ""])
def test_unconfigured_token_is_503(
    anonymous: TestClient, monkeypatch: pytest.MonkeyPatch, configured: str | None
) -> None:
    monkeypatch.setattr(settings, "admin_api_token", configured)

    response = patch(anonymous, 1, {"is_active": False}, TEST_ADMIN_TOKEN)

    assert response.status_code == 503


def test_unknown_source_is_404(client: TestClient) -> None:
    response = patch(client, 999999, {"is_active": False}, TEST_ADMIN_TOKEN)

    assert response.status_code == 404
    assert response.json()["detail"] == "Source not found"


def test_source_is_turned_off_and_on_again(client: TestClient) -> None:
    source_id = create_source(client)

    turned_off = patch(client, source_id, {"is_active": False}, TEST_ADMIN_TOKEN)
    listed = client.get("/api/v1/sources").json()
    turned_on = patch(client, source_id, {"is_active": True}, TEST_ADMIN_TOKEN)

    assert turned_off.status_code == 200
    assert turned_off.json()["is_active"] is False
    assert turned_off.json()["name"] == FEED["name"]
    assert listed[0]["is_active"] is False
    assert turned_on.json()["is_active"] is True


@pytest.mark.parametrize("body", [{}, {"is_active": "maybe"}])
def test_invalid_body_is_422(client: TestClient, body: dict) -> None:
    source_id = create_source(client)

    assert patch(client, source_id, body, TEST_ADMIN_TOKEN).status_code == 422
