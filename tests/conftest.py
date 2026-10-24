import uuid
from collections.abc import Callable, Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.pool import StaticPool

import app.db.base  # noqa: F401  (registers all models on Base.metadata)
from app.db.session import Base
from tests.pg_support import (
    ADMIN_URL,
    TEST_ADMIN_TOKEN,
    alembic_upgrade,
    client_for,
    requires_postgres,
)


@pytest.fixture(autouse=True)
def no_full_text_downloads(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ingestion would download article pages; tests that need it pass a fake extractor."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "ingestion_full_text", False)


@pytest.fixture(autouse=True)
def admin_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Admin endpoints need a configured token; test clients send TEST_ADMIN_TOKEN."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "admin_api_token", TEST_ADMIN_TOKEN)


@pytest.fixture(autouse=True)
def fresh_search_rate_limit() -> Generator[None, None, None]:
    """The search rate limiter is process-wide; no test may inherit another's hits."""
    from app.api.deps import search_rate_limiter

    search_rate_limiter.reset()
    yield
    search_rate_limiter.reset()


@pytest.fixture
def new_postgres_db() -> Generator[Callable[[], str], None, None]:
    """Factory for empty, uniquely named PostgreSQL databases that are dropped afterwards."""
    created: list[str] = []
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT") if ADMIN_URL else None

    def factory() -> str:
        assert admin is not None
        name = f"ainis_pytest_{uuid.uuid4().hex[:12]}"
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
        created.append(name)
        return make_url(ADMIN_URL).set(database=name).render_as_string(hide_password=False)

    yield factory
    if admin is not None:
        with admin.connect() as conn:
            for name in created:
                conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=requires_postgres)])
def engine(request: pytest.FixtureRequest, new_postgres_db: Callable[[], str]) -> Generator[Engine]:
    """Migrated, empty database: in-memory SQLite, or a throwaway PostgreSQL via Alembic."""
    if request.param == "sqlite":
        eng = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(eng)
    else:
        url = new_postgres_db()
        alembic_upgrade(url)
        eng = create_engine(url, connect_args={"options": "-c timezone=UTC"})
    yield eng
    eng.dispose()


@pytest.fixture
def client(engine: Engine) -> Generator[TestClient]:
    yield from client_for(engine)
