"""Collecting from more source types: news API searches and full-text extraction."""

import socket
from collections.abc import Generator
from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.db.base  # noqa: F401  (registers all models on Base.metadata)
from app.db.session import Base
from app.models.article import Article
from app.repositories.source import SourceRepository
from app.schemas.source import SourceCreate
from app.services.feed import FeedClient
from app.services.ingestion import IngestionService
from app.services.news_api import GNewsClient

API_KEY = "gnews-secret-key"
FEED_URL = "https://daily.example/rss.xml"

SHORT_SNIPPET = "A short snippet."
FULL_TEXT = "The full article text. " * 60

FEED = f"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>Daily</title>
  <item><title>Short item</title><link>https://daily.example/short</link>
    <description>{SHORT_SNIPPET}</description></item>
  <item><title>Long item</title><link>https://daily.example/long</link>
    <description>{FULL_TEXT}</description></item>
  <item><title>Title only</title><link>https://daily.example/title-only</link></item>
</channel></rss>""".encode()

GNEWS_RESPONSE = {
    "totalArticles": 3,
    "articles": [
        {
            "title": "Toyota unveils a new EV",
            "description": "Toyota showed its new car.",
            "content": "Toyota showed its new electric car in Tokyo today... [2345 chars]",
            "url": "https://cars.example/toyota-ev",
            "publishedAt": "2026-10-15T08:30:00Z",
            "source": {"name": "Cars Daily", "url": "https://cars.example"},
        },
        {"title": "No link", "description": "Skipped.", "url": "", "publishedAt": None},
        {"title": "", "description": "No title.", "url": "https://cars.example/untitled"},
    ],
}


@pytest.fixture(autouse=True)
def fake_public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolve every host to a public IP so the SSRF check runs without real DNS."""

    def getaddrinfo(host: str, port: int, *args: object, **kwargs: object) -> list:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)


@pytest.fixture
def db() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as session:
        yield session


class FakeExtractor:
    """Serves article pages from a dict; a missing page means extraction failed."""

    def __init__(self, pages: dict[str, str]):
        self.pages = pages
        self.requested: list[str] = []

    def extract_from_url(self, url: str) -> str | None:
        self.requested.append(url)
        page = self.pages.get(url)
        if isinstance(page, Exception):
            raise page
        return page


class FakeGNews:
    """Answers like the GNews search endpoint and records every request."""

    def __init__(self, response: httpx.Response | None = None):
        self.response = response or httpx.Response(200, json=GNEWS_RESPONSE)
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.response


def gnews_client(fake: FakeGNews, api_key: str | None = API_KEY) -> GNewsClient:
    return GNewsClient(api_key=api_key, base_url="https://gnews.test/api/v4",
                       timeout_seconds=5, transport=httpx.MockTransport(fake.handle))


def feed_client() -> FeedClient:
    return FeedClient(5, transport=httpx.MockTransport(
        lambda request: httpx.Response(200, content=FEED)))


def add_rss_source(db: Session) -> None:
    SourceRepository(db).create(SourceCreate(name="Daily", feed_url=FEED_URL))


def add_news_api_source(db: Session, query: str = "toyota") -> None:
    SourceRepository(db).create(
        SourceCreate(name=f"News: {query}", type="news_api", query=query, language="en")
    )


def articles_by_url(db: Session) -> dict[str, Article]:
    return {article.url: article for article in db.scalars(select(Article))}


# --- creating sources -------------------------------------------------------------------


def test_a_news_api_source_is_created_with_its_query(client: TestClient) -> None:
    response = client.post("/api/v1/sources", json={
        "name": "Toyota news", "type": "news_api", "query": "toyota", "language": "en"})

    assert response.status_code == 201
    body = response.json()
    assert (body["type"], body["query"], body["feed_url"]) == ("news_api", "toyota", None)


def test_an_rss_source_is_still_the_default(client: TestClient) -> None:
    response = client.post("/api/v1/sources", json={"name": "Daily", "feed_url": FEED_URL})

    assert response.status_code == 201
    assert (response.json()["type"], response.json()["query"]) == ("rss", None)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"name": "No feed"}, "RSS sources need a feed_url"),
        ({"name": "Both", "feed_url": FEED_URL, "query": "toyota"},
         "RSS sources do not take a query"),
        ({"name": "No query", "type": "news_api"}, "news_api sources need a query"),
        ({"name": "Both", "type": "news_api", "query": "toyota", "feed_url": FEED_URL},
         "news_api sources do not take a feed_url"),
        ({"name": "Unknown", "type": "twitter", "query": "toyota"}, "rss"),
    ],
)
def test_fields_must_match_the_source_type(
    client: TestClient, payload: dict, message: str
) -> None:
    response = client.post("/api/v1/sources", json=payload)

    assert response.status_code == 422
    assert message in response.text


# --- news API sources -------------------------------------------------------------------


def test_news_api_source_saves_the_matching_articles(db: Session) -> None:
    add_news_api_source(db, "toyota")
    fake = FakeGNews()

    result = IngestionService(db, news_client=gnews_client(fake)).run()

    assert result.errors == []
    assert (result.articles_seen, result.articles_created) == (1, 1)  # invalid ones skipped
    article = articles_by_url(db)["https://cars.example/toyota-ev"]
    assert article.title == "Toyota unveils a new EV"
    assert article.content == "Toyota showed its new electric car in Tokyo today"
    assert article.published_at == datetime(2026, 10, 15, 8, 30, tzinfo=UTC)
    assert article.status == "analyzed"
    params = fake.requests[0].url.params
    assert (params["q"], params["lang"], params["max"], params["apikey"]) == (
        "toyota", "en", "10", API_KEY)


def test_news_api_and_rss_sources_are_collected_in_one_run(db: Session) -> None:
    add_rss_source(db)
    add_news_api_source(db)

    result = IngestionService(
        db, feed_client=feed_client(), news_client=gnews_client(FakeGNews())
    ).run()

    assert result.errors == []
    assert result.sources_processed == 2
    assert {"https://daily.example/short", "https://cars.example/toyota-ev"} <= set(
        articles_by_url(db))


def test_missing_api_key_fails_only_that_source(db: Session) -> None:
    add_rss_source(db)
    add_news_api_source(db)

    result = IngestionService(
        db, feed_client=feed_client(), news_client=gnews_client(FakeGNews(), api_key=None)
    ).run()

    assert len(result.errors) == 1 and "NEWS_API_KEY" in result.errors[0]
    assert "https://daily.example/short" in articles_by_url(db)


@pytest.mark.parametrize(
    "response",
    [httpx.Response(401, json={"errors": ["bad key"]}), httpx.Response(200, text="not json")],
)
def test_api_failures_are_reported_without_the_api_key(
    db: Session, response: httpx.Response
) -> None:
    add_news_api_source(db)

    result = IngestionService(db, news_client=gnews_client(FakeGNews(response))).run()

    assert len(result.errors) == 1
    assert "News API" in result.errors[0]
    assert API_KEY not in result.errors[0]
    assert articles_by_url(db) == {}


# --- full-text extraction ---------------------------------------------------------------


def test_short_snippets_are_replaced_by_the_full_article(db: Session) -> None:
    add_rss_source(db)
    extractor = FakeExtractor({
        "https://daily.example/short": FULL_TEXT,
        "https://daily.example/title-only": FULL_TEXT,
    })

    IngestionService(db, feed_client=feed_client(), extractor=extractor).run()

    stored = articles_by_url(db)
    assert stored["https://daily.example/short"].content == FULL_TEXT.strip()
    title_only = stored["https://daily.example/title-only"]
    assert (title_only.content, title_only.status) == (FULL_TEXT.strip(), "analyzed")
    assert "https://daily.example/long" not in extractor.requested  # already long enough


@pytest.mark.parametrize("page", [None, "Tiny.", RuntimeError("parser crashed")])
def test_the_snippet_is_kept_when_extraction_does_not_help(db: Session, page: object) -> None:
    add_rss_source(db)
    extractor = FakeExtractor({"https://daily.example/short": page})

    result = IngestionService(db, feed_client=feed_client(), extractor=extractor).run()

    assert result.errors == []
    assert articles_by_url(db)["https://daily.example/short"].content == SHORT_SNIPPET


def test_news_api_snippets_are_also_extended(db: Session) -> None:
    add_news_api_source(db)
    extractor = FakeExtractor({"https://cars.example/toyota-ev": FULL_TEXT})

    IngestionService(db, news_client=gnews_client(FakeGNews()), extractor=extractor).run()

    assert articles_by_url(db)["https://cars.example/toyota-ev"].content == FULL_TEXT.strip()


def test_full_text_extraction_can_be_switched_off(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "ingestion_full_text", False)
    assert IngestionService(db).extractor is None

    monkeypatch.setattr(settings, "ingestion_full_text", True)
    assert IngestionService(db).extractor is not None

