"""require_admin with session cookies (SQLite): roles, CSRF, X-Admin-Token precedence,
fallback to the token check, and the per-role search limit.

Admin requests use inputs that fail validation or lookup (422/404) right after the
permission check, or ingest an unknown source (200, nothing processed), so no download,
model or background job is started.
"""

from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.auth_deps import login_failure_limiter
from app.core.config import settings
from app.db.session import Base
from app.models.user import User, UserSession
from app.services.passwords import hash_password
from tests.pg_support import TEST_ADMIN_TOKEN, client_for

PASSWORD = "a long enough password"
CSRF = {"X-Requested-With": "ainis"}

# (method, path, request kwargs); every route that depends on require_admin.
PROTECTED = [
    ("POST", "/api/v1/sources", {"json": {}}),
    ("PATCH", "/api/v1/sources/999999", {"json": {"is_active": False}}),
    ("DELETE", "/api/v1/sources/999999", {}),
    ("POST", "/api/v1/ingestion/run", {"params": {"source_id": 999999}}),
    ("POST", "/api/v1/ai/process", {"json": {"limit": 1}}),  # below AI_MIN_DOCUMENTS: 422
    ("GET", "/api/v1/ai/process/no-such-job", {}),
    ("POST", "/api/v1/ai/ask", {"json": {"input": "x"}}),  # too short: 422
]
MUTATING = [entry for entry in PROTECTED if entry[0] != "GET"]
ids = [f"{method} {path}" for method, path, _ in PROTECTED]
mutating_ids = [f"{method} {path}" for method, path, _ in MUTATING]


@pytest.fixture(autouse=True)
def fast_auth(monkeypatch: pytest.MonkeyPatch) -> Generator[None]:
    monkeypatch.setattr(settings, "password_scrypt_n", 16)
    login_failure_limiter.reset()
    yield
    login_failure_limiter.reset()


@pytest.fixture
def sqlite_engine() -> Generator[Engine]:
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def client(sqlite_engine: Engine) -> Generator[TestClient]:
    """A client without the default X-Admin-Token header."""
    for test_client in client_for(sqlite_engine):
        test_client.headers.pop("X-Admin-Token", None)
        yield test_client


def add_user(engine: Engine, username: str, role: str) -> None:
    with Session(engine) as db:
        db.add(User(username=username, password_hash=hash_password(PASSWORD), role=role))
        db.commit()


def sign_in(client: TestClient, engine: Engine, role: str) -> None:
    """Create an account with `role` and log the client in (cookie kept by the client)."""
    add_user(engine, role, role)
    response = client.post("/api/v1/auth/login", json={"username": role, "password": PASSWORD})
    assert response.status_code == 200


def send(client: TestClient, method: str, path: str, kwargs: dict, headers: dict | None = None):
    return client.request(method, path, headers=headers or {}, **kwargs)


@pytest.mark.parametrize(("method", "path", "kwargs"), PROTECTED, ids=ids)
def test_anonymous_is_401(client: TestClient, method, path, kwargs) -> None:
    assert send(client, method, path, kwargs).status_code == 401


@pytest.mark.parametrize(("method", "path", "kwargs"), PROTECTED, ids=ids)
def test_plain_user_is_403(client, sqlite_engine, method, path, kwargs) -> None:
    sign_in(client, sqlite_engine, "user")
    response = send(client, method, path, kwargs, CSRF)
    assert response.status_code == 403
    assert response.json() == {"detail": "Admin role required"}


@pytest.mark.parametrize(("method", "path", "kwargs"), PROTECTED, ids=ids)
def test_admin_session_passes(client, sqlite_engine, method, path, kwargs) -> None:
    sign_in(client, sqlite_engine, "admin")
    response = send(client, method, path, kwargs, CSRF)
    assert response.status_code in {200, 404, 422}, response.text


@pytest.mark.parametrize(("method", "path", "kwargs"), MUTATING, ids=mutating_ids)
def test_admin_change_without_csrf_header_is_403(client, sqlite_engine, method, path, kwargs):
    sign_in(client, sqlite_engine, "admin")
    assert send(client, method, path, kwargs).status_code == 403


@pytest.mark.parametrize(("method", "path", "kwargs"), MUTATING, ids=mutating_ids)
def test_admin_change_from_another_origin_is_403(client, sqlite_engine, method, path, kwargs):
    sign_in(client, sqlite_engine, "admin")
    headers = {**CSRF, "Origin": "https://evil.example"}
    assert send(client, method, path, kwargs, headers).status_code == 403


def test_get_with_cookie_needs_no_csrf_header(client, sqlite_engine) -> None:
    sign_in(client, sqlite_engine, "admin")
    assert client.get("/api/v1/ai/process/no-such-job").status_code == 404


def test_valid_token_without_cookie_passes(client: TestClient) -> None:
    headers = {"X-Admin-Token": TEST_ADMIN_TOKEN}
    assert client.delete("/api/v1/sources/999999", headers=headers).status_code == 404


@pytest.mark.parametrize("token", ["wrong-token", ""])
def test_bad_token_wins_over_admin_cookie(client, sqlite_engine, token: str) -> None:
    sign_in(client, sqlite_engine, "admin")
    headers = {**CSRF, "X-Admin-Token": token}
    assert client.delete("/api/v1/sources/999999", headers=headers).status_code == 401


def test_valid_token_needs_no_csrf_even_with_cookie(client, sqlite_engine) -> None:
    sign_in(client, sqlite_engine, "user")
    headers = {"X-Admin-Token": TEST_ADMIN_TOKEN}
    assert client.delete("/api/v1/sources/999999", headers=headers).status_code == 404


def test_expired_admin_session_falls_back_to_token_check(
    client, sqlite_engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    sign_in(client, sqlite_engine, "admin")
    with Session(sqlite_engine) as db:
        db.execute(update(UserSession).values(expires_at=datetime.now(UTC) - timedelta(1)))
        db.commit()
    assert client.delete("/api/v1/sources/999999", headers=CSRF).status_code == 401
    # Without a server token it is still "not signed in" (401), never the 503 of (a).
    monkeypatch.setattr(settings, "admin_api_token", None)
    response = client.delete("/api/v1/sources/999999", headers=CSRF)
    assert response.status_code == 401
    assert response.json() == {"detail": "Not signed in."}


@pytest.mark.parametrize("configured", [None, ""])
def test_revoked_admin_session_without_server_token_is_401(
    client, sqlite_engine, monkeypatch: pytest.MonkeyPatch, configured
) -> None:
    sign_in(client, sqlite_engine, "admin")
    with Session(sqlite_engine) as db:
        db.execute(delete(UserSession))  # e.g. ended by a password change elsewhere
        db.commit()
    monkeypatch.setattr(settings, "admin_api_token", configured)
    for method, path, kwargs in PROTECTED:
        response = send(client, method, path, kwargs, CSRF)
        assert response.status_code == 401, (method, path)
        assert response.json() == {"detail": "Not signed in."}


def test_token_header_without_server_token_is_503(
    client, sqlite_engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    sign_in(client, sqlite_engine, "admin")  # a valid admin cookie does not change it
    monkeypatch.setattr(settings, "admin_api_token", None)
    response = client.get(
        "/api/v1/ai/process/no-such-job", headers={"X-Admin-Token": TEST_ADMIN_TOKEN}
    )
    assert response.status_code == 503


def test_disabled_admin_falls_back_to_token_check(client, sqlite_engine) -> None:
    sign_in(client, sqlite_engine, "admin")
    with Session(sqlite_engine) as db:
        db.execute(update(User).values(is_active=False))
        db.commit()
    assert client.get("/api/v1/ai/process/no-such-job").status_code == 401


def search_statuses(client: TestClient, times: int) -> list[int]:
    return [
        client.post("/api/v1/ai/search", json={"input": "openai"}).status_code
        for _ in range(times)
    ]


def test_signed_in_users_get_the_higher_search_limit(
    client, sqlite_engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    news_search = pytest.importorskip("app.services.news_search")
    monkeypatch.setattr(news_search.NewsSearchService, "search", lambda self, query: [])
    monkeypatch.setattr(settings, "ai_search_rate_per_minute", 1)
    monkeypatch.setattr(settings, "ai_search_user_rate_per_minute", 3)

    assert search_statuses(client, 2) == [200, 429]  # anonymous, per socket peer
    sign_in(client, sqlite_engine, "user")
    assert search_statuses(client, 4) == [200, 200, 200, 429]  # per user id
