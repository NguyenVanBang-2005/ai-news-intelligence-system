"""Migration 0007 adds the nullable sync columns to sources, and its downgrade removes them."""

from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

from tests.pg_support import requires_postgres
from tests.test_database_migrations import migrate

PREVIOUS_HEAD = "0006_ai_job_active_key"
SYNC_HEAD = "0007_source_sync_status"
SYNC_COLUMNS = {"last_synced_at", "last_status", "last_error"}


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=requires_postgres)])
def database_url(
    request: pytest.FixtureRequest, tmp_path: Path, new_postgres_db: Callable[[], str]
) -> str:
    """An empty database: a SQLite file, or a throwaway PostgreSQL database."""
    if request.param == "sqlite":
        return f"sqlite:///{(tmp_path / 'sync.db').as_posix()}"
    return new_postgres_db()


def source_columns(url: str) -> set[str]:
    engine = create_engine(url)
    try:
        return {column["name"] for column in inspect(engine).get_columns("sources")}
    finally:
        engine.dispose()


def run_sql(url: str, statement: str) -> list:
    """Execute one statement in its own transaction and return any rows."""
    engine = create_engine(url)
    try:
        with engine.begin() as conn:
            result = conn.execute(text(statement))
            return result.all() if result.returns_rows else []
    finally:
        engine.dispose()


def test_migrations_have_a_single_head() -> None:
    heads = migrate("sqlite://", "heads").strip().splitlines()

    assert len(heads) == 1, heads


def test_upgrade_adds_null_columns_and_downgrade_removes_them(database_url: str) -> None:
    migrate(database_url, "upgrade", PREVIOUS_HEAD)
    assert not SYNC_COLUMNS & source_columns(database_url)
    run_sql(
        database_url,
        "INSERT INTO sources (name, type, feed_url, language, is_active) "
        "VALUES ('Old', 'rss', 'https://old.example/rss', 'en', TRUE)",
    )

    migrate(database_url, "upgrade", SYNC_HEAD)
    assert SYNC_COLUMNS <= source_columns(database_url)
    rows = run_sql(database_url, "SELECT last_synced_at, last_status, last_error FROM sources")
    assert [tuple(row) for row in rows] == [(None, None, None)]

    migrate(database_url, "downgrade", PREVIOUS_HEAD)
    assert not SYNC_COLUMNS & source_columns(database_url)
    assert run_sql(database_url, "SELECT name FROM sources")[0][0] == "Old"

    migrate(database_url, "upgrade", "head")
    assert SYNC_COLUMNS <= source_columns(database_url)
