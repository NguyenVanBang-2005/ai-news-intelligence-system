import socket
from collections.abc import Generator
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.orm.exc import DetachedInstanceError
from sqlalchemy.pool import StaticPool

import app.db.base  # noqa: F401  (registers all models on Base.metadata)
from app.db.session import Base
from app.models.article import Article
from app.repositories.article import ArticleRepository
from app.repositories.source import SourceRepository
from app.schemas.source import SourceCreate
from app.services.feed import FeedClient
from app.services.ingestion import IngestionService

FIXTURES = Path(__file__).parent / "fixtures"
DAILY_URL = "https://ai-daily.example/rss.xml"
WEEKLY_URL = "https://ai-weekly.example/rss.xml"
DAILY_COPY_URL = "https://ai-daily-mirror.example/rss.xml"  # sources.feed_url is unique
FEEDS = {
    DAILY_URL: (FIXTURES / "ai_feed.xml").read_bytes(),
    DAILY_COPY_URL: (FIXTURES / "ai_feed.xml").read_bytes(),
    WEEKLY_URL: (FIXTURES / "second_feed.xml").read_bytes(),
}


@pytest.fixture(autouse=True)
def fake_public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    def getaddrinfo(host: str, port: int, *args: object, **kwargs: object) -> list:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)


@pytest.fixture
def db() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    # Default expire_on_commit=True, like the application session.
    with sessionmaker(bind=engine)() as session:
        yield session


class StubSource:
    """ORM-like source whose named attributes raise, as a detached instance would."""

    def __init__(self, failing: tuple[str, ...] = (), **values: object) -> None:
        self._failing = failing
        self._values = values

    def __getattr__(self, name: str) -> object:
        if name in self._failing:
            raise DetachedInstanceError(f"Instance is not bound to a Session ({name})")
        return self._values[name]


def add_source(db: Session, name: str, feed_url: str) -> int:
    return SourceRepository(db).create(
        SourceCreate(name=name, feed_url=feed_url, language="en")
    ).id


def stub(db: Session, name: str, feed_url: str, **kwargs: object) -> StubSource:
    source_id = add_source(db, name, feed_url)
    values = {"id": source_id, "name": name, "feed_url": feed_url, "is_active": True}
    return StubSource(**kwargs, **values)


def service_with(db: Session, sources: list[StubSource]) -> IngestionService:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=FEEDS[str(request.url)])

    client = FeedClient(5, transport=httpx.MockTransport(handler))
    service = IngestionService(db, feed_client=client)
    service.sources = SimpleNamespace(  # type: ignore[assignment]
        list=lambda active_only=False: sources, get=lambda source_id: sources[0]
    )
    return service


def urls(db: Session) -> set[str]:
    return set(db.scalars(select(Article.url)))


def test_name_read_error_is_isolated_and_next_source_ingests(db: Session) -> None:
    broken = stub(db, "Broken", DAILY_URL, failing=("name",))
    good = stub(db, "Good", WEEKLY_URL)

    result = service_with(db, [broken, good]).run()

    assert result.sources_processed == 2
    assert len(result.errors) == 1
    assert result.errors[0].startswith("source #1: DetachedInstanceError")
    assert (result.articles_seen, result.articles_created, result.duplicates_skipped) == (2, 2, 0)
    assert len(urls(db)) == 2
    assert "https://ai-weekly.example/eu-guidance" in urls(db)


def test_id_read_error_uses_own_name_not_previous_source(db: Session) -> None:
    first = stub(db, "First OK", DAILY_URL)
    second = stub(db, "Second Bad", WEEKLY_URL, failing=("id",))
    third = stub(db, "Third OK", DAILY_COPY_URL)

    result = service_with(db, [first, second, third]).run()

    assert result.sources_processed == 3
    assert len(result.errors) == 1
    assert result.errors[0].startswith("Second Bad: DetachedInstanceError")
    assert "First OK" not in result.errors[0]
    # First stores 5; the failing source stores nothing; Third sees the same 5 as duplicates.
    assert (result.articles_seen, result.articles_created, result.duplicates_skipped) == (10, 5, 5)
    assert len(urls(db)) == 5


def test_is_active_read_error_by_source_id_is_reported_not_raised(db: Session) -> None:
    broken = stub(db, "Inactive Check Fails", DAILY_URL, failing=("is_active",))

    result = service_with(db, [broken]).run(source_id=broken.id)

    assert result.sources_processed == 1
    assert len(result.errors) == 1
    assert result.errors[0].startswith("Inactive Check Fails: DetachedInstanceError")
    assert (result.articles_seen, result.articles_created, result.duplicates_skipped) == (0, 0, 0)
    assert urls(db) == set()


def test_inactive_source_by_source_id_is_not_processed(db: Session) -> None:
    inactive = stub(db, "Off", DAILY_URL)
    inactive._values["is_active"] = False

    result = service_with(db, [inactive]).run(source_id=inactive.id)

    assert (result.sources_processed, result.articles_seen, result.errors) == (0, 0, [])


def test_refresh_failure_after_commit_keeps_counters_and_rows_consistent(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken_refresh(*args: object, **kwargs: object) -> None:
        raise OperationalError("SELECT", {}, Exception("connection lost after commit"))

    source = stub(db, "Daily", DAILY_URL)
    monkeypatch.setattr(Session, "refresh", broken_refresh)

    result = service_with(db, [source]).run()

    assert result.errors == []
    assert result.articles_created == result.articles_seen == 5
    assert len(urls(db)) == 5


def test_create_returns_usable_committed_article(db: Session) -> None:
    source_id = add_source(db, "Daily", DAILY_URL)

    article = ArticleRepository(db).create(
        source_id=source_id, title="T", url="https://x.example/1", content="c"
    )

    assert article.id is not None
    assert article.title == "T"
    assert article.created_at is not None  # server default, loaded lazily after commit
    assert urls(db) == {"https://x.example/1"}
