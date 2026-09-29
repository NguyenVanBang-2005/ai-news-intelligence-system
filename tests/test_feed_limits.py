import socket
from collections.abc import Generator, Iterator
from xml.sax.saxutils import escape

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.db.base  # noqa: F401  (registers all models on Base.metadata)
from app.db.session import Base
from app.models.article import Article
from app.repositories.source import SourceRepository
from app.schemas.source import SourceCreate
from app.services.feed import FeedClient, FeedTooLargeError, valid_article_url
from app.services.ingestion import IngestionService

BIG_URL = "https://big.example/rss.xml"
OK_URL = "https://ok.example/rss.xml"


@pytest.fixture(autouse=True)
def fake_public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    def getaddrinfo(host: str, port: int, *args: object, **kwargs: object) -> list:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)


def rss(*entries: tuple[str, str, str]) -> bytes:
    """Build an RSS document from (title, link, description) tuples."""
    items = "".join(
        f"<item><title>{escape(t)}</title><link>{escape(link)}</link>"
        f"<description>{escape(d)}</description></item>"
        for t, link, d in entries
    )
    return (
        f'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
        f"<title>Feed</title>{items}</channel></rss>"
    ).encode()


def client_for(handler, **kwargs: int) -> FeedClient:
    return FeedClient(timeout_seconds=5, transport=httpx.MockTransport(handler), **kwargs)


def serve(body: bytes):
    return lambda request: httpx.Response(200, content=body)


def test_feed_within_limit_is_parsed() -> None:
    body = rss(("Hello", "https://a.example/1", "Body text"))
    items = client_for(serve(body), max_feed_bytes=len(body)).fetch(OK_URL, 10)

    assert [(i.title, i.url, i.content) for i in items] == [
        ("Hello", "https://a.example/1", "Body text")
    ]


def test_oversized_chunked_stream_without_content_length_aborts_early() -> None:
    sent: list[int] = []

    def chunks() -> Iterator[bytes]:
        for index in range(1000):
            sent.append(index)
            yield b"x" * 100

    def handler(request: httpx.Request) -> httpx.Response:
        response = httpx.Response(200, content=chunks())
        assert "content-length" not in response.headers
        return response

    with pytest.raises(FeedTooLargeError):
        client_for(handler, max_feed_bytes=1000).fetch(BIG_URL, 10)

    # 11 chunks cross the 1000-byte limit; the remaining ones were never pulled.
    assert len(sent) < 20


def test_declared_content_length_over_limit_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 500, headers={"Content-Length": "500"})

    with pytest.raises(FeedTooLargeError):
        client_for(handler, max_feed_bytes=100).fetch(BIG_URL, 10)


def test_long_content_is_truncated_and_unicode_kept() -> None:
    long_body = "Trí tuệ nhân tạo " * 200
    body = rss(("Tiêu đề 日本語 🤖", "https://a.example/u", long_body))

    (item,) = client_for(serve(body), max_content_chars=100).fetch(OK_URL, 10)

    assert item.title == "Tiêu đề 日本語 🤖"
    assert len(item.content) <= 100
    assert item.content.endswith("…")
    assert item.content.startswith("Trí tuệ nhân tạo")


def test_invalid_entries_are_dropped_and_valid_ones_kept() -> None:
    long_url = "https://a.example/" + "p" * 1500  # 1518 chars
    body = rss(
        ("Good", "https://a.example/good", "ok"),
        ("<b> </b>", "https://a.example/empty-title", "title is empty after cleaning"),
        ("Bad scheme", "ftp://a.example/file", "x"),
        ("JS scheme", "javascript:alert(1)", "x"),
        ("Credentials", "https://user:pw@a.example/secret", "x"),
        ("User only", "https://user@a.example/secret", "x"),
        ("Too long", long_url, "x"),
        ("Bad port", "https://a.example:notaport/x", "x"),
        ("Also good", "  https://b.example/ünï  ", "ok"),
    )

    items = client_for(serve(body)).fetch(OK_URL, 50)

    assert [i.url for i in items] == ["https://a.example/good", "https://b.example/ünï"]


@pytest.mark.parametrize(
    "url", ["https:///path", "http://", "https://:443/x", "//a.example/x", None]
)
def test_urls_without_hostname_are_rejected(url: str | None) -> None:
    # feedparser may rewrite such links before we see them, so check the validator directly.
    assert valid_article_url(url) is None


def test_url_at_length_limit_is_accepted() -> None:
    url = "https://a.example/" + "p" * (1500 - len("https://a.example/"))
    assert len(url) == 1500

    (item,) = client_for(serve(rss(("Edge", url, "x")))).fetch(OK_URL, 10)

    assert item.url == url


@pytest.fixture
def db() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as session:
        yield session


def test_oversized_feed_is_reported_and_next_source_still_runs(db: Session) -> None:
    ok_body = rss(
        ("Valid", "https://ok.example/1", "content"),
        ("", "https://ok.example/no-title", "dropped"),
        ("Bad link", "ftp://ok.example/2", "dropped"),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == BIG_URL:
            return httpx.Response(200, content=iter([b"x" * 400] * 50))
        return httpx.Response(200, content=ok_body)

    repo = SourceRepository(db)
    repo.create(SourceCreate(name="A Big", feed_url=BIG_URL, language="en"))
    repo.create(SourceCreate(name="B Ok", feed_url=OK_URL, language="en"))
    feed_client = client_for(handler, max_feed_bytes=len(ok_body) + 10)

    result = IngestionService(db, feed_client=feed_client).run()

    assert result.sources_processed == 2
    assert len(result.errors) == 1
    assert result.errors[0].startswith("A Big: FeedTooLargeError")
    # Dropped entries are not counted as seen.
    assert result.articles_seen == 1
    assert result.articles_created == 1
    assert result.duplicates_skipped == 0
    assert [a.url for a in db.scalars(select(Article))] == ["https://ok.example/1"]
