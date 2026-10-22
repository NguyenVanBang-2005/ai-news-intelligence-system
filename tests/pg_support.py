"""Shared helpers for tests that run on SQLite and, when available, a real PostgreSQL.

PostgreSQL tests need a *test* server: set TEST_POSTGRES_ADMIN_URL to a URL for that
server's maintenance database (e.g. .../postgres). Each test creates and drops its own
uniquely named database there, so no existing database is touched. They are skipped
when the variable is unset.
"""

import os
import subprocess
import sys
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.session import get_db, get_session_factory
from app.main import app
from tests.db_isolation import isolated_env

ROOT = Path(__file__).resolve().parents[1]
ADMIN_URL = os.environ.get("TEST_POSTGRES_ADMIN_URL")

requires_postgres = pytest.mark.skipif(
    not ADMIN_URL, reason="TEST_POSTGRES_ADMIN_URL is not set (no PostgreSQL test server)"
)


def alembic_upgrade(url: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT, env=isolated_env(url), capture_output=True, text=True, check=True,
    )


def client_for(eng: Engine, **kwargs: bool) -> Generator[TestClient]:
    factory = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)

    def override_db() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_session_factory] = lambda: factory
    try:
        with TestClient(app, **kwargs) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def count(eng: Engine, model: type) -> int:
    with Session(eng) as session:
        return session.scalar(select(func.count()).select_from(model)) or 0
