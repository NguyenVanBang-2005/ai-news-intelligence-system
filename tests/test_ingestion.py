import socket
from collections.abc import Generator
from pathlib import Path

import feedparser
import httpx
import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError, OperationalError, PendingRollbackError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.db.base  # noqa: F401  (registers all models on Base.metadata)
from app.db.session import Base
from app.models.article import Article
from app.repositories.source import SourceRepository
from app.schemas.source import SourceCreate
from app.services.feed import FeedClient
from app.services.ingestion import IngestionService

FIXTURES = Path(__file__).parent / "fixtures"
AI_FEED_URL = "https://ai-daily.example/rss.xml"
SECOND_FEED_URL = "https://ai-weekly.example/rss.xml"
BROKEN_FEED_URL = "https://broken.example/rss.xml"

FEEDS = {
    AI_FEED_URL: (FIXTURES / "ai_feed.xml").read_bytes(),
    SECOND_FEED_URL: (FIXTURES / "second_feed.xml").read_bytes(),
}


def serve_fixtures(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if url == BROKEN_FEED_URL:
        return httpx.Response(500, text="upstream exploded")
    if url in FEEDS:
        return httpx.Response(200, content=FEEDS[url], headers={"Content-Type": "application/xml"})
    return httpx.Response(404)


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


def add_source(db: Session, name: str, feed_url: str) -> None:
    SourceRepository(db).create(SourceCreate(name=name, feed_url=feed_url, language="en"))


def make_service(db: Session) -> IngestionService:
    feed_client = FeedClient(timeout_seconds=5, transport=httpx.MockTransport(serve_fixtures))
    return IngestionService(db, feed_client=feed_client)


def articles_by_url(db: Session) -> dict[str, Article]:
    return {article.url: article for article in db.scalars(select(Article))}


def test_ingests_new_articles_with_clean_text(db: Session) -> None:
    add_source(db, "AI Daily", AI_FEED_URL)

    result = make_service(db).run()

    assert result.errors == []
    assert result.sources_processed == 1
    # 6 entries in the fixture, one has no link and is dropped by the feed client.
    assert result.articles_seen == 5
    assert result.articles_created == 5
    assert result.duplicates_skipped == 0

    stored = articles_by_url(db)
    gpt = stored["https://ai-daily.example/gpt-agents"]
    assert gpt.title == "OpenAI’s new GPT model & agents"
    assert gpt.author == "Jane Doe"
    assert gpt.content == (
        "The new language model ships with tool use.\n"
        "It scores 92% on the \"AgentBench\" benchmark…\n"
        "Pricing:€20/month."
    )
    assert "<" not in gpt.content and "&" not in gpt.content
    assert "trackPageView" not in gpt.content and "color: red" not in gpt.content
    assert gpt.status == "analyzed"
    assert gpt.topic == "Generative AI"
    assert gpt.summary and "<" not in gpt.summary
    assert gpt.published_at is not None

    # Full <content:encoded> wins over the short <description> teaser.
    funding = stored["https://ai-daily.example/robotics-funding"]
    assert funding.content == (
        "Funding round\n"
        "A humanoid robot startup closed a $50M round.\n"
        "Lead investor: Example Capital\n"
        "Valuation: undisclosed"
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://ai-daily.example/no-body",
        "https://ai-daily.example/repeat",
        "https://ai-daily.example/markup-only",
    ],
)
def test_articles_without_content_are_flagged(db: Session, url: str) -> None:
    add_source(db, "AI Daily", AI_FEED_URL)

    make_service(db).run()

    article = articles_by_url(db)[url]
    assert article.content == ""
    assert article.status == "missing_content"
    # The baseline analyzer still produces a title-based summary and topic.
    assert article.summary == f"{article.title}."
    assert article.topic is not None


def test_duplicate_urls_are_skipped_across_runs_and_sources(db: Session) -> None:
    add_source(db, "AI Daily", AI_FEED_URL)
    add_source(db, "AI Weekly", SECOND_FEED_URL)
    service = make_service(db)

    first = service.run()
    second = service.run()

    # AI Weekly re-publishes the GPT article URL already stored from AI Daily.
    assert first.articles_seen == 7
    assert first.articles_created == 6
    assert first.duplicates_skipped == 1
    assert second.articles_created == 0
    assert second.duplicates_skipped == 7
    stored = articles_by_url(db)
    assert len(stored) == 6
    assert stored["https://ai-daily.example/gpt-agents"].title.startswith("OpenAI’s")


def test_broken_feed_is_reported_and_later_sources_still_run(db: Session) -> None:
    # Sources run in name order, so the broken one is processed first.
    add_source(db, "A Broken Feed", BROKEN_FEED_URL)
    add_source(db, "B AI Weekly", SECOND_FEED_URL)

    result = make_service(db).run()

    assert result.sources_processed == 2
    assert len(result.errors) == 1
    assert result.errors[0].startswith("A Broken Feed: HTTPStatusError")
    assert result.articles_created == 2
    assert set(articles_by_url(db)) == {
        "https://ai-daily.example/gpt-agents",
        "https://ai-weekly.example/eu-guidance",
    }


def fail_article_inserts(db: Session, make_error, only_first: bool = True) -> None:
    """Make INSERTs into articles raise (once by default), like a broken DB write."""
    state = {"armed": True}

    @event.listens_for(db.get_bind(), "before_cursor_execute")
    def _fail(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        if state["armed"] and statement.lstrip().upper().startswith("INSERT INTO ARTICLES"):
            state["armed"] = not only_first
            raise make_error()


def operational_error() -> OperationalError:
    return OperationalError("INSERT INTO articles", {}, Exception("disk I/O error"))


def test_failed_write_puts_session_in_rollback_state(db: Session) -> None:
    add_source(db, "AI Daily", AI_FEED_URL)
    fail_article_inserts(db, operational_error)

    db.add(Article(source_id=1, title="t", url="https://x.example/a"))
    with pytest.raises(OperationalError):
        db.flush()
    with pytest.raises(PendingRollbackError):
        db.execute(select(Article.id))
    db.rollback()
    assert db.execute(select(Article.id)).all() == []


def test_write_error_is_rolled_back_and_next_source_still_ingests(db: Session) -> None:
    add_source(db, "A AI Daily", AI_FEED_URL)
    add_source(db, "B AI Weekly", SECOND_FEED_URL)
    fail_article_inserts(db, operational_error)

    result = make_service(db).run()

    assert result.sources_processed == 2
    assert result.articles_seen == 3  # A stopped at its first item, B saw both
    assert result.articles_created == 2
    assert result.duplicates_skipped == 0
    assert len(result.errors) == 1
    assert result.errors[0].startswith("A AI Daily: OperationalError")
    assert set(articles_by_url(db)) == {
        "https://ai-daily.example/gpt-agents",
        "https://ai-weekly.example/eu-guidance",
    }


def test_committed_articles_survive_later_write_error(db: Session) -> None:
    add_source(db, "AI Daily", AI_FEED_URL)
    state = {"inserts": 0}

    @event.listens_for(db.get_bind(), "before_cursor_execute")
    def _fail_third(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        if statement.lstrip().upper().startswith("INSERT INTO ARTICLES"):
            state["inserts"] += 1
            if state["inserts"] == 3:
                raise operational_error()

    result = make_service(db).run()

    assert result.articles_created == 2
    assert len(result.errors) == 1
    assert len(articles_by_url(db)) == 2


def test_url_inserted_between_exists_and_insert_counts_as_duplicate(db: Session) -> None:
    add_source(db, "AI Daily", AI_FEED_URL)
    service = make_service(db)
    racing_url = "https://ai-daily.example/gpt-agents"
    original_create = service.articles.create
    raced = {"done": False}

    def racing_create(**values: object) -> Article:
        # Another connection wins the race right before our insert.
        if values["url"] == racing_url and not raced["done"]:
            raced["done"] = True
            with Session(db.get_bind()) as other:
                other.add(Article(source_id=1, title="Winner", url=racing_url, content="x"))
                other.commit()
        return original_create(**values)

    service.articles.create = racing_create  # type: ignore[method-assign]

    result = service.run()

    assert result.errors == []
    assert result.articles_seen == 5
    assert result.articles_created == 4
    assert result.duplicates_skipped == 1
    stored = articles_by_url(db)
    assert len(stored) == 5
    assert stored[racing_url].title == "Winner"


def test_non_url_integrity_error_is_an_error_not_a_duplicate(db: Session) -> None:
    add_source(db, "A AI Daily", AI_FEED_URL)
    add_source(db, "B AI Weekly", SECOND_FEED_URL)
    fail_article_inserts(db, lambda: IntegrityError("INSERT", {}, Exception("NOT NULL failed")))

    result = make_service(db).run()

    assert result.duplicates_skipped == 0
    assert len(result.errors) == 1
    assert result.errors[0].startswith("A AI Daily: IntegrityError")
    assert result.articles_created == 2


@pytest.mark.parametrize("path", ["topic/artificial-intelligence2", "2026/example-article"])
def test_html_source_reports_unsupported_feed(db: Session, path: str) -> None:
    # Synthetic HTML, not a captured MIT response. Links must not trigger crawling.
    url = f"https://news.mit.edu/{path}"
    html = b'<html><body><article><a href="/2026/story">Story</a></article></body></html>'
    # Reproduce the old parser behavior: no exception, no feed entries for HTML.
    parsed = feedparser.parse(html)
    assert not parsed.version
    assert parsed.entries == []
    requested = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(200, content=html, headers={"Content-Type": "text/html"})

    add_source(db, "HTML source", url)
    result = IngestionService(
        db, feed_client=FeedClient(5, transport=httpx.MockTransport(handler))
    ).run()

    assert requested == [url]
    assert result.sources_processed == 1
    assert (result.articles_seen, result.articles_created, result.duplicates_skipped) == (0, 0, 0)
    assert len(result.errors) == 1
    assert "UnsupportedFeedError" in result.errors[0]
    assert "HTTP 200, Content-Type: text/html" in result.errors[0]
    assert "source.feed_url" in result.errors[0]
    assert articles_by_url(db) == {}


def test_html_source_does_not_stop_valid_rss(db: Session) -> None:
    add_source(db, "A HTML", "https://html.example/topic")
    add_source(db, "B RSS", SECOND_FEED_URL)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "html.example":
            return httpx.Response(200, text="<html><body>News</body></html>")
        return serve_fixtures(request)

    result = IngestionService(
        db, feed_client=FeedClient(5, transport=httpx.MockTransport(handler))
    ).run()
    assert result.sources_processed == 2
    assert (result.articles_seen, result.articles_created, result.duplicates_skipped) == (2, 2, 0)
    assert len(result.errors) == 1
    assert "UnsupportedFeedError" in result.errors[0]
    assert len(articles_by_url(db)) == 2


@pytest.mark.parametrize(
    "body",
    [
        b'<rss version="2.0"><channel><title>Empty RSS</title></channel></rss>',
        b'<feed xmlns="http://www.w3.org/2005/Atom"><title>Empty Atom</title></feed>',
    ],
)
def test_valid_empty_feed_is_not_an_error(db: Session, body: bytes) -> None:
    add_source(db, "Empty", AI_FEED_URL)
    client = FeedClient(
        5, transport=httpx.MockTransport(lambda r: httpx.Response(200, content=body))
    )
    result = IngestionService(db, feed_client=client).run()
    assert (result.articles_seen, result.articles_created, result.duplicates_skipped) == (0, 0, 0)
    assert result.errors == []


def test_recognized_rss_with_mislabelled_content_type_still_works(db: Session) -> None:
    add_source(db, "RSS", SECOND_FEED_URL)
    client = FeedClient(5, transport=httpx.MockTransport(lambda r: httpx.Response(
        200, content=FEEDS[SECOND_FEED_URL], headers={"Content-Type": "text/html"}
    )))
    result = IngestionService(db, feed_client=client).run()
    assert (result.articles_seen, result.articles_created, result.duplicates_skipped) == (2, 2, 0)
    assert result.errors == []


def test_endpoint_uses_saved_source_url_and_reports_html_error(db: Session, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.db.session import get_db
    from app.main import app

    saved_url = "https://news.mit.edu/topic/artificial-intelligence2"
    add_source(db, "Saved HTML", saved_url)
    source_id = SourceRepository(db).list()[0].id
    requested = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(200, text="<html><body>Topic</body></html>")

    feed = FeedClient(5, transport=httpx.MockTransport(handler))
    monkeypatch.setattr("app.services.ingestion.FeedClient", lambda timeout: feed)
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)  # no lifespan: never initialize the configured application DB
    try:
        response = client.post(
            "/api/v1/ingestion/run",
            params={"source_id": source_id},
            json={"url": SECOND_FEED_URL},  # endpoint has no body parameter
        )
    finally:
        client.close()
        app.dependency_overrides.pop(get_db, None)
    assert requested == [saved_url]
    assert response.status_code == 200
    result = response.json()
    assert result["articles_seen"] == result["articles_created"] == 0
    assert result["duplicates_skipped"] == 0
    assert len(result["errors"]) == 1
    assert "UnsupportedFeedError" in result["errors"][0]


def test_long_unicode_content_is_truncated_before_analyzer_and_storage(db: Session) -> None:
    from xml.sax.saxutils import escape

    from app.services.analyzer import HeuristicAnalyzer

    limit = 120
    long_body = "Trí tuệ nhân tạo 🤖 học máy 日本語. " * 100
    body = (
        '<rss version="2.0"><channel><title>F</title><item>'
        "<title>Tiêu đề mô hình ngôn ngữ</title><link>https://u.example/long</link>"
        f"<description>{escape(long_body)}</description></item></channel></rss>"
    ).encode()
    add_source(db, "Unicode", AI_FEED_URL)
    client = FeedClient(
        5, transport=httpx.MockTransport(lambda r: httpx.Response(200, content=body)),
        max_content_chars=limit,
    )
    service = IngestionService(db, feed_client=client)
    real_analyzer = service.analyzer
    calls: list[tuple[str, str]] = []

    class SpyAnalyzer:
        def analyze(self, title: str, content: str):  # real analysis, inputs recorded
            calls.append((title, content))
            return real_analyzer.analyze(title, content)

    service.analyzer = SpyAnalyzer()  # type: ignore[assignment]

    result = service.run()

    assert (result.articles_seen, result.articles_created, result.duplicates_skipped) == (1, 1, 0)
    assert result.errors == []
    (article,) = articles_by_url(db).values()
    assert len(calls) == 1
    analyzed_title, analyzed_content = calls[0]
    assert len(long_body.strip()) > limit
    assert len(analyzed_content) <= limit and analyzed_content.endswith("…")
    assert analyzed_content.startswith("Trí tuệ nhân tạo 🤖")
    assert article.content == analyzed_content  # DB stores exactly what the analyzer saw
    assert article.title == analyzed_title == "Tiêu đề mô hình ngôn ngữ"
    assert article.status == "analyzed"
    expected = HeuristicAnalyzer().analyze(analyzed_title, analyzed_content)
    assert (article.summary, article.topic) == (expected.summary, expected.topic)


def test_non_url_integrity_error_is_not_duplicate_even_if_url_exists(db: Session) -> None:
    # A real NOT NULL failure (source_id) on a row whose URL is also already stored.
    # Only a *unique URL* violation may count as duplicate; this must be reported as an error.
    add_source(db, "AI Daily", AI_FEED_URL)
    source_id = SourceRepository(db).list()[0].id
    existing = "https://ai-daily.example/gpt-agents"
    db.add(Article(source_id=source_id, title="Existing", url=existing, content="x"))
    db.commit()
    service = make_service(db)
    original_create = service.articles.create
    # Simulate the race window: the exists pre-check misses, and the insert is also malformed.
    service.articles.exists_by_url = lambda url: False  # type: ignore[method-assign]
    service.articles.create = (  # type: ignore[method-assign]
        lambda **values: original_create(**{**values, "source_id": None})
    )

    result = service.run()

    assert result.articles_seen == 1  # source aborted at its first item
    assert result.duplicates_skipped == 0
    assert result.articles_created == 0
    assert len(result.errors) == 1 and result.errors[0].startswith("AI Daily: IntegrityError")
    assert [a.title for a in db.scalars(select(Article))] == ["Existing"]


class FakeDriverError(Exception):
    """Stand-in for a psycopg error; mocks metadata only, no PostgreSQL is contacted."""

    def __init__(self, message: str, pgcode: str | None, constraint: str | None) -> None:
        super().__init__(message)
        self.pgcode = pgcode
        self.diag = type("Diag", (), {"constraint_name": constraint})()


@pytest.mark.parametrize(
    ("orig", "expected"),
    [
        (Exception("UNIQUE constraint failed: articles.url"), True),
        (Exception("UNIQUE constraint failed: articles.id"), False),
        (Exception("UNIQUE constraint failed: articles.url, articles.title"), False),
        (Exception("NOT NULL constraint failed: articles.source_id"), False),
        (Exception("FOREIGN KEY constraint failed"), False),
        (FakeDriverError("dup", "23505", "ix_articles_url"), True),
        (FakeDriverError("dup", "23505", "articles_pkey"), False),
        (FakeDriverError("dup", "23505", None), False),
        (FakeDriverError("null", "23502", "ix_articles_url"), False),
    ],
)
def test_url_unique_violation_detection(orig: Exception, expected: bool) -> None:
    from app.repositories.article import is_url_unique_violation

    assert is_url_unique_violation(IntegrityError("INSERT", {}, orig)) is expected


def test_endpoint_failed_and_duplicate_sources_do_not_block_next(db: Session, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.db.session import get_db
    from app.main import app

    add_source(db, "A Broken", BROKEN_FEED_URL)
    add_source(db, "B Daily", AI_FEED_URL)
    add_source(db, "C Weekly", SECOND_FEED_URL)  # re-publishes B's gpt-agents URL
    feed = FeedClient(5, transport=httpx.MockTransport(serve_fixtures))
    monkeypatch.setattr("app.services.ingestion.FeedClient", lambda timeout: feed)
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    try:
        response = client.post("/api/v1/ingestion/run")
    finally:
        client.close()
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    result = response.json()
    assert result["sources_processed"] == 3
    assert result["articles_seen"] == 7
    assert result["articles_created"] == 6
    assert result["duplicates_skipped"] == 1
    assert len(result["errors"]) == 1
    assert result["errors"][0].startswith("A Broken: HTTPStatusError")
    assert len(articles_by_url(db)) == 6
