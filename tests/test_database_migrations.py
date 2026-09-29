import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.article import Article
from app.models.source import Source
from app.repositories.article import ArticleRepository
from app.services.feed import FeedClient
from tests.db_isolation import isolated_env

ROOT = Path(__file__).resolve().parents[1]


def migrate(url: str, *args: str) -> str:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=ROOT,
        env=isolated_env(url),
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def test_migration_roundtrip_and_utc(tmp_path: Path) -> None:
    url = f"sqlite:///{(tmp_path / 'migration.db').as_posix()}"
    migrate(url, "upgrade", "head")
    migrate(url, "upgrade", "head")  # repeated deploy is safe
    migrate(url, "check")  # migration matches ORM metadata
    engine = create_engine(url)
    try:
        with Session(engine) as db:
            source = Source(name="Test", feed_url="https://example.com/rss")
            db.add(source)
            db.flush()
            db.add_all([
                Article(source_id=source.id, title="Dated", url="https://example.com/1",
                        published_at=datetime(2026, 9, 29, 7,
                                              tzinfo=timezone(timedelta(hours=7)))),
                Article(source_id=source.id, title="Undated", url="https://example.com/2"),
            ])
            db.commit()
            db.expire_all()
            rows, total = ArticleRepository(db).list(topic=None, status=None, limit=10, offset=0)
            assert total == 2
            assert rows[0].title == "Dated"
            assert rows[0].published_at == datetime(2026, 9, 29, tzinfo=UTC)
            assert rows[0].published_at.utcoffset() == timedelta(0)
            assert rows[0].created_at.utcoffset() == timedelta(0)
            assert source.created_at.utcoffset() == timedelta(0)
        migrate(url, "downgrade", "base")
        assert set(inspect(engine).get_table_names()) == {"alembic_version"}
        migrate(url, "upgrade", "head")
    finally:
        engine.dispose()


def test_postgres_migration_sql() -> None:
    sql = migrate("postgresql+psycopg://news:news@localhost/news", "upgrade", "head", "--sql")
    assert "TIMESTAMP WITH TIME ZONE" in sql
    assert "CREATE UNIQUE INDEX ix_articles_url" in sql
    assert "FOREIGN KEY(source_id) REFERENCES sources (id)" in sql


def test_compose_database_url_escapes_special_password_characters() -> None:
    password = "p@ss:w/rd#%?&= x"
    settings = Settings(
        _env_file=None,
        database_url="sqlite://",  # ignored: POSTGRES_HOST takes precedence
        postgres_host="db",
        postgres_port=5432,
        postgres_user="news",
        postgres_password=password,
        postgres_db="news",
    )

    parsed = make_url(settings.database_url)
    assert parsed.drivername == "postgresql+psycopg"
    assert (parsed.host, parsed.port, parsed.database, parsed.username) == (
        "db", 5432, "news", "news"
    )
    assert parsed.password == password  # round-trips: the raw URL was escaped
    assert password not in settings.database_url


def test_migration_ignores_ambient_postgres_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Simulate a shell/.env that points at a real PostgreSQL; it must not be touched.
    monkeypatch.setenv("POSTGRES_HOST", "postgres-must-not-be-used.invalid")
    monkeypatch.setenv("POSTGRES_PASSWORD", "secret")
    url = f"sqlite:///{(tmp_path / 'isolated.db').as_posix()}"

    effective = subprocess.run(
        [sys.executable, "-c",
         "from app.core.config import settings; print(settings.database_url)"],
        cwd=ROOT, env=isolated_env(url), capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert effective == url

    migrate(url, "upgrade", "head")  # would fail to connect if POSTGRES_HOST leaked in
    engine = create_engine(url)
    try:
        assert {"sources", "articles", "alembic_version"} <= set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_isolated_env_beats_fake_dotenv_with_postgres_host(tmp_path: Path) -> None:
    # A .env in the subprocess cwd (a temp dir; the real .env is not touched) tries to
    # redirect the database. Settings reads ".env" from cwd, so cwd=tmp_path exercises it.
    (tmp_path / ".env").write_text(
        "POSTGRES_HOST=dotenv-host.invalid\nPOSTGRES_PASSWORD=x\n"
        "DATABASE_URL=postgresql+psycopg://a:b@dotenv-db.invalid/x\n",
        encoding="utf-8",
    )
    code = "from app.core.config import settings; print(settings.database_url)"
    url = f"sqlite:///{(tmp_path / 'isolated.db').as_posix()}"

    def effective_url(env: dict[str, str]) -> str:
        return subprocess.run(
            [sys.executable, "-c", code],
            cwd=tmp_path, env={**env, "PYTHONPATH": str(ROOT)},
            capture_output=True, text=True, check=True,
        ).stdout.strip()

    # Control: without isolation the fake .env does win, so this test can detect leaks.
    ambient = {k: v for k, v in os.environ.items()
               if k not in {"DATABASE_URL"} and not k.startswith("POSTGRES_")}
    assert "dotenv-host.invalid" in effective_url(ambient)
    assert effective_url(isolated_env(url)) == url


def test_postgres_host_requires_password() -> None:
    with pytest.raises(ValidationError, match="POSTGRES_PASSWORD"):
        Settings(_env_file=None, postgres_host="db")


def test_database_url_is_used_without_postgres_host() -> None:
    url = "postgresql+psycopg://u:p@localhost:5432/x"
    assert Settings(_env_file=None, database_url=url).database_url == url


def test_feed_dates_normalized_to_utc() -> None:
    for raw in ("2026-09-29T07:00:00+07:00", "2026-09-29T00:00:00"):
        item = FeedClient(5)._to_item({
            "title": "Test", "link": "https://example.com/1", "published": raw,
        })
        assert item.published_at == datetime(2026, 9, 29, tzinfo=UTC)
        assert item.published_at.utcoffset() == timedelta(0)
