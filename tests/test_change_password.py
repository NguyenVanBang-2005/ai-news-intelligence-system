"""POST /auth/change-password on SQLite, plus /auth/me fields and logout clearing the DB row."""

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.auth_deps import login_failure_limiter, register_rate_limiter
from app.core.config import settings
from app.db.session import Base
from app.main import app
from app.models.user import User, UserSession
from app.services.passwords import verify_password
from tests.pg_support import client_for

OLD = "a long enough password"
NEW = "another long password"
CSRF = {"X-Requested-With": "ainis"}
PATH = "/api/v1/auth/change-password"


@pytest.fixture(autouse=True)
def fast_auth(monkeypatch: pytest.MonkeyPatch) -> Generator[None]:
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


@pytest.fixture
def alice(client: TestClient) -> TestClient:
    """`client` signed in as alice (password OLD)."""
    body = {"username": "alice", "password": OLD}
    assert client.post("/api/v1/auth/register", json=body).status_code == 201
    assert login(client).status_code == 200
    return client


def login(client: TestClient, password: str = OLD):
    return client.post("/api/v1/auth/login", json={"username": "alice", "password": password})


def change(client: TestClient, current: str = OLD, new: str = NEW, headers=CSRF):
    body = {"current_password": current, "new_password": new}
    return client.post(PATH, json=body, headers=headers)


def stored_hash(engine: Engine) -> str:
    with Session(engine) as db:
        return db.scalar(select(User.password_hash).where(User.username == "alice"))


def session_count(engine: Engine) -> int:
    with Session(engine) as db:
        return db.scalar(select(func.count()).select_from(UserSession))


def test_success_rehashes_with_scrypt_and_returns_204(
    alice: TestClient, sqlite_engine: Engine
) -> None:
    before = stored_hash(sqlite_engine)
    response = change(alice)

    assert response.status_code == 204
    assert response.content == b""
    after = stored_hash(sqlite_engine)
    assert after != before
    assert after.startswith("scrypt$")
    assert verify_password(NEW, after) and not verify_password(OLD, after)


def test_old_password_no_longer_logs_in(alice: TestClient) -> None:
    assert change(alice).status_code == 204
    assert login(alice, OLD).status_code == 401
    assert login(alice, NEW).status_code == 200


def test_current_session_still_works(alice: TestClient) -> None:
    assert change(alice).status_code == 204
    me = alice.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["username"] == "alice"


def test_other_sessions_are_revoked(alice: TestClient, sqlite_engine: Engine) -> None:
    other = TestClient(app)  # a second browser: same app and database, its own cookie jar
    assert login(other).status_code == 200
    assert other.get("/api/v1/auth/me").status_code == 200
    assert session_count(sqlite_engine) == 2

    assert change(alice).status_code == 204

    assert other.get("/api/v1/auth/me").status_code == 401
    assert alice.get("/api/v1/auth/me").status_code == 200
    assert session_count(sqlite_engine) == 1


def test_wrong_current_password_is_400_and_changes_nothing(
    alice: TestClient, sqlite_engine: Engine
) -> None:
    before = stored_hash(sqlite_engine)
    response = change(alice, current="not the password")

    assert response.status_code == 400
    assert response.json() == {"detail": "Current password is incorrect"}
    assert stored_hash(sqlite_engine) == before
    assert alice.get("/api/v1/auth/me").status_code == 200  # a wrong guess keeps the session


def test_new_password_equal_to_username_is_422(client: TestClient) -> None:
    username = "bob_123456"
    password = "bob's long password"
    client.post("/api/v1/auth/register", json={"username": username, "password": password})
    client.post("/api/v1/auth/login", json={"username": username, "password": password})
    response = change(client, current=password, new="BOB_123456")

    assert response.status_code == 422
    assert response.json() == {"detail": "New password must not be the username"}


def test_too_short_new_password_is_422(alice: TestClient, sqlite_engine: Engine) -> None:
    before = stored_hash(sqlite_engine)
    assert change(alice, new="short").status_code == 422
    assert change(alice, new="x" * 129).status_code == 422
    assert stored_hash(sqlite_engine) == before


def test_new_password_equal_to_current_is_422(alice: TestClient, sqlite_engine: Engine) -> None:
    before = stored_hash(sqlite_engine)
    response = change(alice, new=OLD)

    assert response.status_code == 422
    assert response.json() == {"detail": "New password must be different from the current password"}
    assert stored_hash(sqlite_engine) == before


def test_unknown_fields_are_422(alice: TestClient) -> None:
    body = {"current_password": OLD, "new_password": NEW, "role": "admin"}
    assert alice.post(PATH, json=body, headers=CSRF).status_code == 422


def test_without_cookie_is_401_even_with_the_admin_token(client: TestClient) -> None:
    # client_for sends X-Admin-Token on every request: it is not a user, so it does not count.
    assert "X-Admin-Token" in client.headers
    response = change(client)
    assert response.status_code == 401
    assert response.json() == {"detail": "Not signed in."}


def test_missing_csrf_header_is_403(alice: TestClient, sqlite_engine: Engine) -> None:
    before = stored_hash(sqlite_engine)
    assert change(alice, headers={}).status_code == 403
    assert stored_hash(sqlite_engine) == before


def test_other_origin_is_403(alice: TestClient, sqlite_engine: Engine) -> None:
    before = stored_hash(sqlite_engine)
    assert change(alice, headers={**CSRF, "Origin": "https://evil.example"}).status_code == 403
    assert stored_hash(sqlite_engine) == before
    assert change(alice, headers={**CSRF, "Origin": "http://testserver"}).status_code == 204


def test_repeated_wrong_current_password_is_429(alice: TestClient, sqlite_engine: Engine) -> None:
    for _ in range(settings.auth_login_max_failures):
        assert change(alice, current="not the password").status_code == 400
    locked = change(alice)  # even the right password
    assert locked.status_code == 429
    assert "Retry-After" in locked.headers
    assert verify_password(OLD, stored_hash(sqlite_engine))


def test_correct_current_password_clears_failures(alice: TestClient) -> None:
    for _ in range(settings.auth_login_max_failures - 1):
        change(alice, current="not the password")
    assert change(alice, new=OLD).status_code == 422  # right current password, bad new one
    for _ in range(settings.auth_login_max_failures - 1):
        assert change(alice, current="not the password").status_code == 400


def test_me_returns_only_public_fields(alice: TestClient) -> None:
    me = alice.get("/api/v1/auth/me")
    assert me.json() == {"id": 1, "username": "alice", "role": "user"}
    assert "scrypt" not in me.text


def test_logout_deletes_the_session_row(alice: TestClient, sqlite_engine: Engine) -> None:
    assert session_count(sqlite_engine) == 1
    assert alice.post("/api/v1/auth/logout", headers=CSRF).status_code == 204
    assert session_count(sqlite_engine) == 0
