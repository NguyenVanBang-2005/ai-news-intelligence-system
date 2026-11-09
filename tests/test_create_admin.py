"""scripts/create_admin.py on SQLite: create, promote, validation, output, then login."""

import importlib.util
from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.session import Base
from app.models.user import User
from app.services.auth import create_or_promote_admin, register_user
from tests.pg_support import client_for

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "create_admin.py"
PASSWORD = "a long enough password"
OTHER_PASSWORD = "another long password"


def load_script():
    spec = importlib.util.spec_from_file_location("create_admin", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


create_admin = load_script()


@pytest.fixture(autouse=True)
def fast_scrypt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "password_scrypt_n", 16)


@pytest.fixture
def sqlite_engine() -> Generator[Engine]:
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def factory(sqlite_engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=sqlite_engine, expire_on_commit=False)


def get_user(engine: Engine, username: str) -> User | None:
    with Session(engine) as db:
        return db.scalar(select(User).where(User.username == username))


def no_password_needed() -> str:
    pytest.fail("the password must not be read")


def test_creates_a_new_admin(factory, sqlite_engine) -> None:
    with factory() as db:
        assert create_or_promote_admin(db, " Boss ", lambda: PASSWORD) == "created"
    user = get_user(sqlite_engine, "boss")
    assert user is not None and user.role == "admin" and user.is_active


def test_promotes_an_existing_user_without_touching_the_password(factory, sqlite_engine):
    with factory() as db:
        register_user(db, "carol", PASSWORD)
        db.execute(User.__table__.update().values(is_active=False))
        db.commit()
    before = get_user(sqlite_engine, "carol").password_hash
    with factory() as db:
        assert create_or_promote_admin(db, "carol", no_password_needed) == "promoted"
    after = get_user(sqlite_engine, "carol")
    assert (after.role, after.is_active, after.password_hash) == ("admin", True, before)


def test_reset_password_replaces_the_hash(factory, sqlite_engine) -> None:
    with factory() as db:
        register_user(db, "carol", PASSWORD)
    before = get_user(sqlite_engine, "carol").password_hash
    with factory() as db:
        create_or_promote_admin(db, "carol", lambda: OTHER_PASSWORD, reset_password=True)
    assert get_user(sqlite_engine, "carol").password_hash != before


@pytest.mark.parametrize(
    ("username", "password"),
    [("ab", PASSWORD), ("bad name", PASSWORD), ("boss", "short"), ("boss_admin1", "BOSS_ADMIN1")],
)
def test_invalid_input_is_rejected(factory, sqlite_engine, username, password) -> None:
    with factory() as db, pytest.raises(ValueError):
        create_or_promote_admin(db, username, lambda: password)
    with Session(sqlite_engine) as db:
        assert db.scalar(select(User)) is None


def test_cli_output_has_no_secret(factory, sqlite_engine, monkeypatch, capsys) -> None:
    monkeypatch.setenv(create_admin.PASSWORD_ENV_VAR, PASSWORD)
    assert create_admin.main(["--username", "Boss"], session_factory=factory) == 0
    output = capsys.readouterr()
    assert output.out.strip() == "Admin 'boss' created"
    stored_hash = get_user(sqlite_engine, "boss").password_hash
    for secret in (PASSWORD, stored_hash):
        assert secret not in output.out + output.err


def test_cli_reports_invalid_password(factory, monkeypatch, capsys) -> None:
    monkeypatch.setenv(create_admin.PASSWORD_ENV_VAR, "tiny-pass")
    assert create_admin.main(["--username", "boss"], session_factory=factory) == 1
    output = capsys.readouterr()
    assert output.err.startswith("Error: password must be 10-128 characters")
    assert "tiny-pass" not in output.out + output.err


def test_cli_rejects_a_password_argument(factory) -> None:
    with pytest.raises(SystemExit):
        create_admin.main(["--username", "boss", "--password", PASSWORD], session_factory=factory)


def test_created_admin_can_log_in(factory, sqlite_engine, monkeypatch) -> None:
    monkeypatch.setenv(create_admin.PASSWORD_ENV_VAR, PASSWORD)
    create_admin.main(["--username", "boss"], session_factory=factory)
    for client in client_for(sqlite_engine):
        response = client.post(
            "/api/v1/auth/login", json={"username": "boss", "password": PASSWORD}
        )
        assert response.status_code == 200
        assert response.json()["role"] == "admin"
