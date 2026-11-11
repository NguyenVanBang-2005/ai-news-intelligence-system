"""Sign-in core on SQLite: register, login, session cookie, /me, logout, CSRF, limits."""

import hashlib
from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.auth_deps import login_failure_limiter, register_rate_limiter
from app.core.config import settings
from app.db.session import Base
from app.models.user import User, UserSession
from tests.pg_support import client_for

PASSWORD = "a long enough password"
CSRF = {"X-Requested-With": "ainis"}


@pytest.fixture(autouse=True)
def fast_auth(monkeypatch: pytest.MonkeyPatch) -> Generator[None]:
    """Cheap hashing and empty limiters for every test."""
    monkeypatch.setattr(settings, "password_scrypt_n", 16)
    login_failure_limiter.reset()
    register_rate_limiter.reset()
    yield
    login_failure_limiter.reset()
    register_rate_limiter.reset()


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
    yield from client_for(sqlite_engine)


def register(client: TestClient, username: str = "alice", password: str = PASSWORD):
    return client.post("/api/v1/auth/register", json={"username": username, "password": password})


def login(client: TestClient, username: str = "alice", password: str = PASSWORD):
    return client.post("/api/v1/auth/login", json={"username": username, "password": password})


def test_register_creates_a_plain_user(client: TestClient) -> None:
    response = register(client, username="  Alice ")
    assert response.status_code == 201
    assert response.json() == {"id": 1, "username": "alice", "role": "user"}
    assert "password" not in response.text


def test_register_rejects_a_role_in_the_body(client: TestClient, sqlite_engine: Engine) -> None:
    body = {"username": "mallory", "password": PASSWORD, "role": "admin"}
    assert client.post("/api/v1/auth/register", json=body).status_code == 422
    with Session(sqlite_engine) as db:
        assert db.scalar(select(User)) is None


def test_duplicate_username_is_409(client: TestClient) -> None:
    assert register(client).status_code == 201
    assert register(client, username="ALICE").status_code == 409


@pytest.mark.parametrize(
    ("username", "password"),
    [("alice", "short"), ("alice_1234", "Alice_1234"), ("ab", PASSWORD), ("bad name", PASSWORD)],
)
def test_invalid_registration_is_422(client: TestClient, username: str, password: str) -> None:
    assert register(client, username=username, password=password).status_code == 422


def test_register_is_rate_limited(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "auth_register_per_hour", 2)
    assert register(client, username="user1").status_code == 201
    assert register(client, username="user2").status_code == 201
    assert register(client, username="user3").status_code == 429


def test_login_sets_a_strict_http_only_cookie(client: TestClient) -> None:
    register(client)
    response = login(client, username="ALICE")
    assert response.status_code == 200
    assert response.json() == {"id": 1, "username": "alice", "role": "user"}
    assert "password" not in response.text
    cookie = response.headers["set-cookie"].lower()
    assert cookie.startswith(f"{settings.session_cookie_name}=")
    for attribute in ("httponly", "samesite=strict", "path=/", "max-age=43200"):
        assert attribute in cookie


def test_wrong_password_and_unknown_user_get_the_same_401(client: TestClient) -> None:
    register(client)
    wrong_password = login(client, password="not the password")
    unknown_user = login(client, username="nobody")
    assert wrong_password.status_code == unknown_user.status_code == 401
    assert wrong_password.json() == unknown_user.json() == {
        "detail": "Invalid username or password"
    }


def test_inactive_user_cannot_log_in(client: TestClient, sqlite_engine: Engine) -> None:
    register(client)
    with Session(sqlite_engine) as db:
        db.execute(update(User).values(is_active=False))
        db.commit()
    assert login(client).json() == {"detail": "Invalid username or password"}


def test_me_follows_the_session(client: TestClient) -> None:
    assert client.get("/api/v1/auth/me").status_code == 401
    register(client)
    login(client)
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["username"] == "alice"
    assert "password" not in me.text
    assert client.post("/api/v1/auth/logout", headers=CSRF).status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401


def test_expired_session_is_401(client: TestClient, sqlite_engine: Engine) -> None:
    register(client)
    login(client)
    with Session(sqlite_engine) as db:
        db.execute(update(UserSession).values(expires_at=datetime.now(UTC) - timedelta(1)))
        db.commit()
    assert client.get("/api/v1/auth/me").status_code == 401


def test_database_stores_only_the_token_hash(client: TestClient, sqlite_engine: Engine) -> None:
    register(client)
    token = login(client).cookies[settings.session_cookie_name]
    with Session(sqlite_engine) as db:
        stored = db.scalars(select(UserSession.token_hash)).all()
    assert stored == [hashlib.sha256(token.encode()).hexdigest()]
    assert token not in stored


def test_login_locks_after_max_failures(client: TestClient) -> None:
    register(client)
    for _ in range(settings.auth_login_max_failures):
        assert login(client, password="not the password").status_code == 401
    locked = login(client)  # even the right password
    assert locked.status_code == 429
    assert "Retry-After" in locked.headers


def test_successful_login_clears_failures(client: TestClient) -> None:
    register(client)
    for _ in range(settings.auth_login_max_failures - 1):
        login(client, password="not the password")
    assert login(client).status_code == 200
    for _ in range(settings.auth_login_max_failures - 1):
        assert login(client, password="not the password").status_code == 401


def count_hashing(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record every password check authenticate() makes (real or dummy)."""
    import app.services.auth as auth_service

    calls: list[str] = []
    real_verify, real_dummy = auth_service.verify_password, auth_service.verify_dummy

    def verify(password: str, stored_hash: str) -> bool:
        calls.append("verify")
        return real_verify(password, stored_hash)

    def dummy(password: str) -> None:
        calls.append("dummy")
        real_dummy(password)

    monkeypatch.setattr(auth_service, "verify_password", verify)
    monkeypatch.setattr(auth_service, "verify_dummy", dummy)
    return calls


def test_login_flood_from_one_address_is_429_without_hashing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = count_hashing(monkeypatch)
    limit = settings.login_ip_max_attempts
    for index in range(limit):
        assert login(client, username=f"random-{index}").status_code == 401
    assert len(calls) == limit
    for index in range(3):
        refused = login(client, username=f"more-{index}")
        assert refused.status_code == 429
        assert int(refused.headers["Retry-After"]) >= 1
    assert len(calls) == limit  # refused attempts never reached scrypt


def test_successful_login_does_not_reset_the_address_limit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "login_ip_max_attempts", 3)
    register(client)
    assert login(client, password="not the password").status_code == 401
    assert login(client).status_code == 200
    assert login(client).status_code == 200
    assert login(client).status_code == 429  # even the right password


def test_address_limit_window_ends(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.auth_deps import login_ip_limiter

    now = [1000.0]
    monkeypatch.setattr(login_ip_limiter, "clock", lambda: now[0])
    monkeypatch.setattr(settings, "login_ip_max_attempts", 1)
    register(client)
    assert login(client).status_code == 200
    assert login(client).status_code == 429
    now[0] += login_ip_limiter.window_seconds + 1
    assert login(client).status_code == 200


def test_logout_without_cookie_is_204(client: TestClient) -> None:
    assert client.post("/api/v1/auth/logout").status_code == 204


def test_logout_with_cookie_needs_the_csrf_header(client: TestClient) -> None:
    register(client)
    login(client)
    assert client.post("/api/v1/auth/logout").status_code == 403
    assert client.get("/api/v1/auth/me").status_code == 200  # session survived


def test_logout_from_another_origin_is_403(client: TestClient) -> None:
    register(client)
    login(client)
    other_site = {**CSRF, "Origin": "https://evil.example"}
    assert client.post("/api/v1/auth/logout", headers=other_site).status_code == 403
    same_site = {**CSRF, "Origin": "http://testserver"}
    assert client.post("/api/v1/auth/logout", headers=same_site).status_code == 204
