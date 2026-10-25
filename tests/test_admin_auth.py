"""Write and costly endpoints need X-Admin-Token; read endpoints stay public.

The protected handlers never run without a valid token, so no network or model is touched
by the 401/503 cases. With a valid token the requests use inputs that fail validation or
lookup (422/404/409) before any download or model load.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from tests.pg_support import TEST_ADMIN_TOKEN

PROTECTED = [
    ("POST", "/api/v1/sources", {"json": {}}),
    ("DELETE", "/api/v1/sources/999999", {}),
    ("POST", "/api/v1/ingestion/run", {"params": {"source_id": 999999}}),
    ("POST", "/api/v1/ai/process", {"json": {}}),
    ("POST", "/api/v1/ai/ask", {"json": {"input": "x"}}),  # too short: 422
]

PUBLIC = [
    "/api/v1/health",
    "/api/v1/articles",
    "/api/v1/topics/trending",
    "/api/v1/ai/topics",
    "/",
]

ids = [f"{method} {path}" for method, path, _ in PROTECTED]


@pytest.fixture
def anonymous(client: TestClient) -> TestClient:
    """The shared client without its default admin header."""
    client.headers.pop("X-Admin-Token", None)
    return client


def call(
    client: TestClient, method: str, path: str, kwargs: dict, token: str | bytes | None = None
):
    headers = {"X-Admin-Token": token} if token is not None else {}
    return client.request(method, path, headers=headers, **kwargs)


@pytest.mark.parametrize(("method", "path", "kwargs"), PROTECTED, ids=ids)
def test_missing_token_is_401(anonymous: TestClient, method, path, kwargs) -> None:
    assert call(anonymous, method, path, kwargs).status_code == 401


@pytest.mark.parametrize(("method", "path", "kwargs"), PROTECTED, ids=ids)
@pytest.mark.parametrize("token", ["wrong-token", "", TEST_ADMIN_TOKEN + "x", "tökén".encode()])
def test_wrong_token_is_401(anonymous: TestClient, method, path, kwargs, token) -> None:
    assert call(anonymous, method, path, kwargs, token).status_code == 401


@pytest.mark.parametrize(("method", "path", "kwargs"), PROTECTED, ids=ids)
def test_valid_token_is_let_through(anonymous: TestClient, method, path, kwargs) -> None:
    response = call(anonymous, method, path, kwargs, TEST_ADMIN_TOKEN)
    assert response.status_code != 401, response.text
    # /ai/process may answer 503 when ML libraries are missing, but never the auth 503.
    assert "ADMIN_API_TOKEN" not in response.text


@pytest.mark.parametrize("configured", [None, ""])
@pytest.mark.parametrize(("method", "path", "kwargs"), PROTECTED, ids=ids)
def test_unconfigured_token_fails_closed(
    anonymous: TestClient, monkeypatch: pytest.MonkeyPatch, configured, method, path, kwargs
) -> None:
    monkeypatch.setattr(settings, "admin_api_token", configured)
    # Even an empty header (which would equal an empty configured token) is refused.
    for token in (None, "", TEST_ADMIN_TOKEN):
        assert call(anonymous, method, path, kwargs, token).status_code == 503


@pytest.mark.parametrize("path", PUBLIC)
def test_public_reads_need_no_token(anonymous: TestClient, path: str) -> None:
    assert anonymous.get(path).status_code == 200


def test_job_status_needs_no_token(anonymous: TestClient) -> None:
    # Unknown job: 404, not 401, so the read path is not behind the token.
    assert anonymous.get("/api/v1/ai/process/unknown").status_code == 404


def test_article_detail_needs_no_token(anonymous: TestClient) -> None:
    assert anonymous.get("/api/v1/articles/999999").status_code == 404
