"""Regression tests for POST /api/v1/sources returning HTTP 500.

Root cause found in the field: the request hit a PostgreSQL database that had no schema
(or no running server). `sources` did not exist, so the INSERT raised
`psycopg.errors.UndefinedTable` -> 500. The route/repository/schema are correct once
`alembic upgrade head` has run.

PostgreSQL cases use the shared fixtures in tests/conftest.py (see tests/pg_support.py).
"""

import socket
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from app.models.article import Article
from app.models.source import Source
from app.repositories.source import SourceRepository
from app.schemas.source import SourceCreate
from app.services.feed import FeedClient
from app.services.ingestion import IngestionService
from tests.pg_support import alembic_upgrade, client_for, count, requires_postgres

FIXTURES = Path(__file__).parent / "fixtures"

SCREENSHOT_PAYLOAD = {
    "name": "Craig Rowe",
    "feed_url": "https://news.mit.edu/2026/craig-rowe-soars-to-new-heights-1001",
    "language": "en",
}
FEED_URL = "https://ai-daily.example/rss.xml"


def test_screenshot_payload_creates_source_and_reads_back_in_utc(
    client: TestClient, engine: Engine
) -> None:
    created = client.post("/api/v1/sources", json=SCREENSHOT_PAYLOAD)

    assert created.status_code == 201
    body = created.json()
    assert body["name"] == "Craig Rowe"
    assert body["feed_url"] == SCREENSHOT_PAYLOAD["feed_url"]  # HTML URL: syntax-only check
    assert body["is_active"] is True

    listed = client.get("/api/v1/sources")
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()] == [body["id"]]
    assert listed.json()[0]["feed_url"] == SCREENSHOT_PAYLOAD["feed_url"]

    for raw in (body["created_at"], listed.json()[0]["created_at"]):
        stamp = datetime.fromisoformat(raw)
        assert stamp.tzinfo is not None
        assert stamp.utcoffset() == timedelta(0)
    assert count(engine, Source) == 1


def test_duplicate_name_is_409_and_next_valid_request_succeeds(
    client: TestClient, engine: Engine
) -> None:
    assert client.post("/api/v1/sources", json=SCREENSHOT_PAYLOAD).status_code == 201

    same_name = {**SCREENSHOT_PAYLOAD, "feed_url": "https://other.example/rss.xml"}
    rejected = client.post("/api/v1/sources", json=same_name)

    assert rejected.status_code == 409
    assert count(engine, Source) == 1
    ok = client.post(
        "/api/v1/sources",
        json={"name": "Another", "feed_url": "https://another.example/rss.xml"},
    )
    assert ok.status_code == 201  # the failed insert did not poison the session/pool
    assert count(engine, Source) == 2


def test_duplicate_feed_url_is_409_and_next_valid_request_succeeds(
    client: TestClient, engine: Engine
) -> None:
    assert client.post("/api/v1/sources", json=SCREENSHOT_PAYLOAD).status_code == 201

    same_url = {**SCREENSHOT_PAYLOAD, "name": "Different Name"}
    rejected = client.post("/api/v1/sources", json=same_url)

    assert rejected.status_code == 409
    assert count(engine, Source) == 1
    ok = client.post(
        "/api/v1/sources",
        json={"name": "Another", "feed_url": "https://another.example/rss.xml"},
    )
    assert ok.status_code == 201
    assert count(engine, Source) == 2


@pytest.mark.parametrize(
    "payload",
    [
        {**SCREENSHOT_PAYLOAD, "feed_url": "not a url"},
        {**SCREENSHOT_PAYLOAD, "feed_url": "ftp://example.com/feed.xml"},
        {**SCREENSHOT_PAYLOAD, "feed_url": "https://"},
        {"name": "Craig Rowe", "language": "en"},
        {"feed_url": SCREENSHOT_PAYLOAD["feed_url"], "language": "en"},
        {},
    ],
    ids=["bad-syntax", "ftp-scheme", "no-host", "missing-feed_url", "missing-name", "empty"],
)
def test_invalid_payload_is_422_and_writes_nothing(
    client: TestClient, engine: Engine, payload: dict
) -> None:
    response = client.post("/api/v1/sources", json=payload)

    assert response.status_code == 422
    assert count(engine, Source) == 0


@requires_postgres
def test_unmigrated_postgres_is_the_real_cause_of_500_until_alembic_runs(
    new_postgres_db: Callable[[], str],
) -> None:
    """The 500 from the screenshot: valid payload, PostgreSQL without a schema."""
    url = new_postgres_db()  # empty database: no tables, no alembic_version
    eng = create_engine(url, connect_args={"options": "-c timezone=UTC"})
    try:
        gen = client_for(eng, raise_server_exceptions=False)
        unmigrated = next(gen)
        response = unmigrated.post("/api/v1/sources", json=SCREENSHOT_PAYLOAD)
        assert response.status_code == 500
        assert response.text == "Internal Server Error"
        next(gen, None)

        # The failure is the missing table, not payload validation or the repository.
        with Session(eng) as session, pytest.raises(ProgrammingError, match="sources"):
            SourceRepository(session).create(SourceCreate(**SCREENSHOT_PAYLOAD))

        alembic_upgrade(url)  # the fix: apply migrations to the new database
        gen = client_for(eng)
        migrated = next(gen)
        assert migrated.post("/api/v1/sources", json=SCREENSHOT_PAYLOAD).status_code == 201
        next(gen, None)
    finally:
        eng.dispose()


def fake_public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    real_getaddrinfo = socket.getaddrinfo

    def getaddrinfo(host: str, port: int, *args: object, **kwargs: object) -> list:
        if host in ("localhost", "127.0.0.1", "::1"):
            return real_getaddrinfo(host, port, *args, **kwargs)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)


def ingestion_service(db: Session) -> IngestionService:
    html = b"<!doctype html><html><head><title>Craig Rowe</title></head><body>Hi</body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == SCREENSHOT_PAYLOAD["feed_url"]:
            return httpx.Response(200, content=html, headers={"content-type": "text/html"})
        return httpx.Response(200, content=(FIXTURES / "ai_feed.xml").read_bytes())

    return IngestionService(db, feed_client=FeedClient(5, transport=httpx.MockTransport(handler)))


def test_ingestion_html_page_reports_unsupported_feed_without_creating_articles(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_public_dns(monkeypatch)
    with Session(engine) as db:
        source_id = SourceRepository(db).create(SourceCreate(**SCREENSHOT_PAYLOAD)).id

        result = ingestion_service(db).run(source_id=source_id)

    assert result.sources_processed == 1
    assert len(result.errors) == 1
    assert result.errors[0].startswith("Craig Rowe: UnsupportedFeedError")
    assert "text/html" in result.errors[0]
    assert (result.articles_seen, result.articles_created) == (0, 0)
    assert count(engine, Article) == 0


def test_html_source_does_not_stop_the_rest_of_the_batch(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_public_dns(monkeypatch)
    with Session(engine) as db:
        repo = SourceRepository(db)
        repo.create(SourceCreate(**SCREENSHOT_PAYLOAD))  # "Craig Rowe" sorts first
        repo.create(SourceCreate(name="Daily Feed", feed_url=FEED_URL))

        result = ingestion_service(db).run()

    assert result.sources_processed == 2
    assert len(result.errors) == 1
    assert result.errors[0].startswith("Craig Rowe: UnsupportedFeedError")
    assert result.articles_created == result.articles_seen == 5
    assert count(engine, Article) == 5
