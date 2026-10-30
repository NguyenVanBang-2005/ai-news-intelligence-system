"""Ingestion records each source's latest sync: last_synced_at, last_status, last_error."""

import socket
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

import app.services.ingestion as ingestion
from app.models.article import Article
from app.models.source import LAST_ERROR_MAX_CHARS, Source
from app.services.feed import FeedClient
from app.services.ingestion import IngestionService
from app.services.safe_http import TooManyRedirectsError
from app.services.sync_errors import UNEXPECTED_ERROR_MESSAGE, short_error_message

FIXTURES = Path(__file__).parent / "fixtures"
GOOD_URL = "https://good-feed.example/rss.xml"
EMPTY_URL = "https://empty-feed.example/rss.xml"
HTML_URL = "https://html-page.example/news"
FAILING_URL = "https://failing-feed.example/rss.xml"
PRIVATE_URL = "https://intranet-feed.example/rss.xml"
LOOP_URL = "https://redirect-loop.example/rss.xml"
PRIVATE_IP = "10.1.2.3"
EMPTY_RSS = b'<rss version="2.0"><channel><title>Empty</title></channel></rss>'


def serve(request: httpx.Request) -> httpx.Response:
    """Fake feed servers: one good, one empty, one HTML page, one failing with HTTP 500."""
    url = str(request.url)
    if url == GOOD_URL:
        return httpx.Response(200, content=(FIXTURES / "ai_feed.xml").read_bytes())
    if url == EMPTY_URL:
        return httpx.Response(200, content=EMPTY_RSS)
    if url == HTML_URL:
        return httpx.Response(200, text="<html><body>Not a feed</body></html>")
    if url == LOOP_URL:  # redirects to itself forever
        return httpx.Response(302, headers={"Location": LOOP_URL})
    return httpx.Response(500, text=f"upstream at {url} exploded")


@pytest.fixture(autouse=True)
def fake_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every host is public except the intranet one, so the SSRF check runs offline."""
    real_getaddrinfo = socket.getaddrinfo

    def getaddrinfo(host: str, port: int, *args: object, **kwargs: object) -> list:
        if host in ("localhost", "127.0.0.1", "::1"):
            return real_getaddrinfo(host, port, *args, **kwargs)
        ip = PRIVATE_IP if host == "intranet-feed.example" else "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)


def add_source(engine: Engine, name: str, feed_url: str, is_active: bool = True) -> int:
    """Store a source directly and return its id."""
    with Session(engine) as db:
        source = Source(name=name, feed_url=feed_url, is_active=is_active)
        db.add(source)
        db.commit()
        return source.id


def run(engine: Engine, source_id: int | None = None, requested: list[str] | None = None):
    """Run ingestion against the fake servers; requested URLs are appended to `requested`."""

    def handler(request: httpx.Request) -> httpx.Response:
        if requested is not None:
            requested.append(str(request.url))
        return serve(request)

    feed_client = FeedClient(5, transport=httpx.MockTransport(handler))
    with Session(engine) as db:
        return IngestionService(db, feed_client=feed_client).run(source_id)


def sync_state(engine: Engine, source_id: int) -> tuple:
    """(last_synced_at, last_status, last_error) as stored in the database."""
    with Session(engine) as db:
        source = db.get(Source, source_id)
        return source.last_synced_at, source.last_status, source.last_error


def article_count(engine: Engine, source_id: int) -> int:
    with Session(engine) as db:
        return db.query(Article).filter(Article.source_id == source_id).count()


# --- ok / warning / error ---------------------------------------------------------------


def test_never_synced_source_has_null_status(engine: Engine) -> None:
    source_id = add_source(engine, "Fresh", GOOD_URL)

    assert sync_state(engine, source_id) == (None, None, None)


def test_feed_with_articles_is_ok(engine: Engine) -> None:
    source_id = add_source(engine, "Good", GOOD_URL)

    run(engine)

    synced_at, status, error = sync_state(engine, source_id)
    assert (status, error) == ("ok", None)
    assert synced_at is not None and synced_at.utcoffset().total_seconds() == 0


def test_feed_with_only_known_articles_is_still_ok(engine: Engine) -> None:
    source_id = add_source(engine, "Good", GOOD_URL)
    run(engine)

    result = run(engine)

    assert result.articles_created == 0 and result.duplicates_skipped > 0
    assert sync_state(engine, source_id)[1] == "ok"


def test_empty_feed_is_a_warning(engine: Engine) -> None:
    source_id = add_source(engine, "Empty", EMPTY_URL)

    result = run(engine)

    assert result.errors == []
    assert sync_state(engine, source_id)[1:] == ("warning", None)


@pytest.mark.parametrize(
    ("feed_url", "expected_error"),
    [
        (HTML_URL, "UnsupportedFeedError: Link returns HTML or another document, not RSS/Atom"),
        (FAILING_URL, "HTTPStatusError: Server answered with an error status"),
        (PRIVATE_URL, "UnsafeFeedUrlError: Blocked non-public or unresolvable address"),
    ],
)
def test_failing_feed_is_an_error_with_a_short_message(
    engine: Engine, feed_url: str, expected_error: str
) -> None:
    source_id = add_source(engine, "Broken", feed_url)

    result = run(engine)

    assert len(result.errors) == 1
    synced_at, status, error = sync_state(engine, source_id)
    assert (status, error) == ("error", expected_error)
    assert synced_at is not None


@pytest.mark.parametrize("feed_url", [HTML_URL, FAILING_URL, PRIVATE_URL])
def test_last_error_never_contains_the_url_host_or_ip(engine: Engine, feed_url: str) -> None:
    source_id = add_source(engine, "Broken", feed_url)

    run(engine)

    error = sync_state(engine, source_id)[2]
    host = feed_url.split("/")[2]
    for secret in (feed_url, host, host.split(".")[0], PRIVATE_IP, "http", "Traceback"):
        assert secret not in error


# --- isolation, inactive sources, source_id ---------------------------------------------


def test_error_in_one_source_keeps_the_other_sources_articles_and_status(
    engine: Engine,
) -> None:
    broken_id = add_source(engine, "A Broken", FAILING_URL)
    good_id = add_source(engine, "B Good", GOOD_URL)

    result = run(engine)

    assert result.sources_processed == 2 and len(result.errors) == 1
    assert sync_state(engine, broken_id)[1] == "error"
    assert sync_state(engine, good_id)[1:] == ("ok", None)
    assert article_count(engine, good_id) == result.articles_created > 0


def test_running_all_sources_skips_inactive_ones(engine: Engine) -> None:
    active_id = add_source(engine, "Active", GOOD_URL)
    inactive_id = add_source(engine, "Inactive", EMPTY_URL, is_active=False)
    requested: list[str] = []

    result = run(engine, requested=requested)

    assert result.sources_processed == 1
    assert EMPTY_URL not in requested
    assert sync_state(engine, inactive_id) == (None, None, None)
    assert sync_state(engine, active_id)[1] == "ok"


def test_inactive_source_by_id_is_not_fetched_or_updated(engine: Engine) -> None:
    inactive_id = add_source(engine, "Inactive", GOOD_URL, is_active=False)
    requested: list[str] = []

    result = run(engine, source_id=inactive_id, requested=requested)

    assert (result.sources_processed, result.errors, requested) == (0, [], [])
    assert sync_state(engine, inactive_id) == (None, None, None)


def test_source_id_updates_only_that_source(engine: Engine) -> None:
    chosen_id = add_source(engine, "Chosen", GOOD_URL)
    other_id = add_source(engine, "Other", EMPTY_URL)

    run(engine, source_id=chosen_id)

    assert sync_state(engine, chosen_id)[1] == "ok"
    assert sync_state(engine, other_id) == (None, None, None)


def test_second_run_moves_last_synced_at_forward(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_id = add_source(engine, "Good", GOOD_URL)
    first_time = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
    second_time = datetime(2026, 10, 1, 9, 30, tzinfo=UTC)

    for now in (first_time, second_time):
        monkeypatch.setattr(ingestion, "datetime", FixedClock(now))
        run(engine)
        assert sync_state(engine, source_id)[0] == now


class FixedClock:
    """Stands in for datetime in app.services.ingestion; now() returns a fixed instant."""

    def __init__(self, instant: datetime) -> None:
        self.instant = instant

    def now(self, tz=None) -> datetime:
        return self.instant


# --- API and message helper -------------------------------------------------------------


def test_sources_api_returns_the_sync_fields(client: TestClient, engine: Engine) -> None:
    fresh_id = add_source(engine, "Fresh", EMPTY_URL, is_active=False)
    broken_id = add_source(engine, "Broken", HTML_URL)
    run(engine)

    by_id = {source["id"]: source for source in client.get("/api/v1/sources").json()}

    fresh, broken = by_id[fresh_id], by_id[broken_id]
    assert (fresh["last_synced_at"], fresh["last_status"], fresh["last_error"]) == (
        None, None, None
    )
    assert broken["last_status"] == "error"
    assert broken["last_error"].startswith("UnsupportedFeedError: ")
    assert broken["last_synced_at"] is not None


def test_unknown_exception_gets_a_generic_message_without_its_text() -> None:
    message = short_error_message(RuntimeError(f"failed at {GOOD_URL} from {PRIVATE_IP}"))

    assert message == f"RuntimeError: {UNEXPECTED_ERROR_MESSAGE}"


def test_message_is_cut_to_the_column_size() -> None:
    long_named = type("E" * 400, (Exception,), {})

    assert len(short_error_message(long_named())) == LAST_ERROR_MAX_CHARS


def test_redirect_loop_gets_its_own_message(engine: Engine) -> None:
    source_id = add_source(engine, "Loop", LOOP_URL)

    run(engine)

    assert sync_state(engine, source_id)[1:] == (
        "error", "TooManyRedirectsError: Too many redirects"
    )


def test_too_many_redirects_is_no_longer_unexpected() -> None:
    message = short_error_message(TooManyRedirectsError("Too many redirects"))

    assert message == "TooManyRedirectsError: Too many redirects"
    assert UNEXPECTED_ERROR_MESSAGE not in message


def test_timeouts_have_their_own_message() -> None:
    message = short_error_message(httpx.ReadTimeout("read timed out at 10.0.0.1"))

    assert message == "ReadTimeout: Request timed out"
