"""scripts/create_admin.py on SQLite: create, reset, promote, validation, output, login."""

import importlib.util
import subprocess
import sys
from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.session import Base
from app.models.user import User, UserSession
from app.services.auth import create_or_promote_admin, create_session, register_user
from tests.db_isolation import isolated_env
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


def session_count(engine: Engine) -> int:
    with Session(engine) as db:
        return db.scalar(select(func.count()).select_from(UserSession))


def test_promote_makes_an_existing_user_an_active_admin_without_touching_the_password(
    factory, sqlite_engine
) -> None:
    with factory() as db:
        register_user(db, "carol", PASSWORD)
        db.execute(User.__table__.update().values(is_active=False))
        db.commit()
    before = get_user(sqlite_engine, "carol").password_hash
    with factory() as db:
        assert create_or_promote_admin(db, "carol", no_password_needed, promote=True) == "promoted"
    after = get_user(sqlite_engine, "carol")
    assert (after.role, after.is_active, after.password_hash) == ("admin", True, before)


def test_reset_password_keeps_a_plain_user_a_plain_user(factory, sqlite_engine) -> None:
    with factory() as db:
        register_user(db, "carol", PASSWORD)
        db.execute(User.__table__.update().values(is_active=False))
        db.commit()
    before = get_user(sqlite_engine, "carol").password_hash
    with factory() as db:
        outcome = create_or_promote_admin(
            db, "carol", lambda: OTHER_PASSWORD, reset_password=True
        )
    after = get_user(sqlite_engine, "carol")
    assert outcome == "password reset"
    assert after.password_hash != before
    assert (after.role, after.is_active) == ("user", False)


def test_reset_password_ends_every_session_of_the_account(factory, sqlite_engine) -> None:
    with factory() as db:
        carol = register_user(db, "carol", PASSWORD)
        dave = register_user(db, "dave", PASSWORD)
        create_session(db, carol)
        create_session(db, carol)
        create_session(db, dave)
    with factory() as db:
        create_or_promote_admin(db, "carol", lambda: OTHER_PASSWORD, reset_password=True)
    with Session(sqlite_engine) as db:
        owners = list(db.scalars(select(UserSession.user_id)))
    assert owners == [dave.id]  # only the other account keeps its session


def test_promote_without_reset_keeps_the_sessions(factory, sqlite_engine) -> None:
    with factory() as db:
        create_session(db, register_user(db, "carol", PASSWORD))
    with factory() as db:
        create_or_promote_admin(db, "carol", no_password_needed, promote=True)
    assert session_count(sqlite_engine) == 1


def test_promote_and_reset_together(factory, sqlite_engine) -> None:
    with factory() as db:
        register_user(db, "carol", PASSWORD)
    with factory() as db:
        outcome = create_or_promote_admin(
            db, "carol", lambda: OTHER_PASSWORD, reset_password=True, promote=True
        )
    assert outcome == "promoted, password reset"
    assert get_user(sqlite_engine, "carol").role == "admin"


def test_existing_account_without_a_flag_changes_nothing(factory, sqlite_engine) -> None:
    with factory() as db:
        register_user(db, "carol", PASSWORD)
    before = get_user(sqlite_engine, "carol")
    with factory() as db, pytest.raises(ValueError, match="--promote"):
        create_or_promote_admin(db, "carol", no_password_needed)
    after = get_user(sqlite_engine, "carol")
    assert (after.role, after.password_hash) == ("user", before.password_hash)


def test_rejected_new_password_changes_nothing(factory, sqlite_engine) -> None:
    with factory() as db:
        create_session(db, register_user(db, "carol", PASSWORD))
    before = get_user(sqlite_engine, "carol").password_hash
    with factory() as db, pytest.raises(ValueError):
        create_or_promote_admin(db, "carol", lambda: "short", reset_password=True, promote=True)
    after = get_user(sqlite_engine, "carol")
    assert (after.role, after.password_hash) == ("user", before)
    assert session_count(sqlite_engine) == 1


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
    assert output.out.splitlines() == ["Database: sqlite://", "Admin 'boss' created"]
    stored_hash = get_user(sqlite_engine, "boss").password_hash
    for secret in (PASSWORD, stored_hash):
        assert secret not in output.out + output.err


def test_cli_reports_invalid_password(factory, monkeypatch, capsys) -> None:
    monkeypatch.setenv(create_admin.PASSWORD_ENV_VAR, "tiny-pass")
    assert create_admin.main(["--username", "boss"], session_factory=factory) == 1
    output = capsys.readouterr()
    assert output.err.startswith("Error: password must be 10-128 characters")
    assert "tiny-pass" not in output.out + output.err


def test_cli_shows_the_database_without_its_password(monkeypatch, capsys) -> None:
    engine = create_engine("postgresql+psycopg://u:SECRET@h/db")  # never connects
    monkeypatch.setattr(create_admin, "create_or_promote_admin", lambda *a, **k: "created")
    try:
        factory = sessionmaker(bind=engine)
        assert create_admin.main(["--username", "boss"], session_factory=factory) == 0
    finally:
        engine.dispose()
    output = capsys.readouterr()
    assert output.out.splitlines()[0] == "Database: postgresql+psycopg://u:***@h/db"
    assert "SECRET" not in output.out + output.err


def test_cli_promote_and_reset_flags(factory, sqlite_engine, monkeypatch, capsys) -> None:
    with factory() as db:
        register_user(db, "carol", PASSWORD)
    monkeypatch.setenv(create_admin.PASSWORD_ENV_VAR, OTHER_PASSWORD)
    reset = ["--username", "carol", "--reset-password"]
    assert create_admin.main(reset, session_factory=factory) == 0
    assert get_user(sqlite_engine, "carol").role == "user"
    assert create_admin.main(["--username", "carol", "--promote"], session_factory=factory) == 0
    assert get_user(sqlite_engine, "carol").role == "admin"
    out = capsys.readouterr().out.splitlines()
    assert out[1] == "Account 'carol': password reset"
    assert out[3] == "Account 'carol': promoted"


def test_cli_existing_account_without_a_flag_is_an_error(factory, capsys) -> None:
    with factory() as db:
        register_user(db, "carol", PASSWORD)
    assert create_admin.main(["--username", "carol"], session_factory=factory) == 1
    assert "--promote" in capsys.readouterr().err


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


def test_script_help_runs_from_the_repo_root_without_pythonpath(tmp_path: Path) -> None:
    # A fresh interpreter, as `python scripts/create_admin.py` or `docker exec` would run it.
    env = isolated_env(f"sqlite:///{(tmp_path / 'unused.db').as_posix()}")
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        cwd=SCRIPT.parents[1], env=env, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "--username" in result.stdout and "--reset-password" in result.stdout
    assert "--promote" in result.stdout
    assert not (tmp_path / "unused.db").exists()  # --help never opens the database
