"""scripts/seed_demo.py on SQLite with fake feeds: no network, no ML model."""

import importlib.util
import socket
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.db.base  # noqa: F401  (registers all models on Base.metadata)
from app.core.config import settings
from app.db.session import Base
from app.models.ai_job import AIJob
from app.models.article import Article
from app.models.source import Source
from app.repositories.source import SourceRepository
from app.schemas.source import SourceCreate
from app.services import ai_jobs
from app.services.feed import FeedClient

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "seed_demo.py"


def load_script():
    spec = importlib.util.spec_from_file_location("seed_demo", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


seed_demo = load_script()
DEMO_URLS = [url for _, url in seed_demo.DEMO_SOURCES]


def rss(feed_url: str, count: int, offset: int = 0) -> bytes:
    """A small RSS feed with `count` items whose links are unique to this feed."""
    slug = feed_url.split("//", 1)[1].split("/", 1)[0].replace(".", "-")
    items = "".join(
        f"<item><title>{slug} story {n}</title>"
        f"<link>https://{slug}.example/story-{n}</link>"
        f"<description>Article {n} about artificial intelligence from {slug}.</description>"
        "<pubDate>Wed, 11 Nov 2026 08:00:00 GMT</pubDate></item>"
        for n in range(offset, offset + count)
    )
    return (
        '<?xml version="1.0"?><rss version="2.0"><channel><title>Feed</title>'
        f"{items}</channel></rss>"
    ).encode()


class FakeFeeds:
    """Serves a feed per URL; URLs in `broken` answer 500. Counts the requests."""

    def __init__(self, items_per_feed: int = 3) -> None:
        self.items_per_feed = items_per_feed
        self.offset = 0
        self.broken: set[str] = set()
        self.requests: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(url)
        if url in self.broken:
            return httpx.Response(500, text="upstream exploded")
        return httpx.Response(
            200,
            content=rss(url, self.items_per_feed, self.offset),
            headers={"Content-Type": "application/rss+xml"},
        )

    def client(self) -> FeedClient:
        return FeedClient(timeout_seconds=5, transport=httpx.MockTransport(self))


@dataclass
class FakeResult:
    documents_received: int
    unique_documents: int
    semantic_duplicates: int
    topics_created: int
    articles_updated: int
    confidence_method: str = "fallback"
    topic_coherence: float | None = None


def fake_process(db: Session, parameters: dict) -> FakeResult:
    """Stands in for TopicModelService.process: marks the batch processed, no ML."""
    articles = list(
        db.scalars(
            select(Article).where(Article.content != "", Article.status != "ai_analyzed")
        )
    )
    for article in articles:
        article.status = "ai_analyzed"
        article.topic = "Demo topic"
    db.commit()
    n = len(articles)
    return FakeResult(n, n, 0, 1, n)


@pytest.fixture(autouse=True)
def fake_public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolve every host to a public IP so the SSRF check runs without real DNS."""

    def getaddrinfo(host: str, port: int, *args: object, **kwargs: object) -> list:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)


@pytest.fixture(autouse=True)
def no_ml(monkeypatch: pytest.MonkeyPatch) -> None:
    """Small batches are enough, the ML import is skipped and the pipeline is faked."""
    monkeypatch.setattr(settings, "ai_min_documents", 2)
    monkeypatch.setattr(seed_demo, "check_ai_dependencies", lambda: None)
    monkeypatch.setattr(ai_jobs, "_process", fake_process)


@pytest.fixture
def engine() -> Generator[Engine]:
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def count(engine: Engine, model, *where) -> int:
    with Session(engine) as db:
        return db.scalar(select(func.count()).select_from(model).where(*where))


def run(factory, feeds: FakeFeeds, *argv: str) -> int:
    return seed_demo.main(list(argv), session_factory=factory, feed_client=feeds.client())


def test_first_run_adds_sources_ingests_and_processes(
    factory, engine, capsys: pytest.CaptureFixture[str]
) -> None:
    feeds = FakeFeeds(items_per_feed=3)

    assert run(factory, feeds) == 0

    assert count(engine, Source) == 4
    assert count(engine, Article) == 12
    assert count(engine, Article, Article.status == "ai_analyzed") == 12
    assert sorted(set(feeds.requests)) == sorted(DEMO_URLS)
    jobs = Session(engine).scalars(select(AIJob)).all()
    assert [job.status for job in jobs] == ["succeeded"]
    assert jobs[0].active_key is None  # the lock is released

    out = capsys.readouterr().out
    assert out.startswith("Database: sqlite://")
    assert "Step 1/3: demo sources" in out
    assert "+ MIT Research: added" in out
    assert "Totals: 4 source(s), 12 article(s), 12 AI-processed" in out


def test_database_line_masks_the_password(capsys: pytest.CaptureFixture[str]) -> None:
    pg_engine = create_engine("postgresql+psycopg://news:s3cret@db:5432/news")
    factory = sessionmaker(bind=pg_engine)
    assert seed_demo.session_factory_database_label(factory) == (
        "postgresql+psycopg://news:***@db:5432/news"
    )


def test_second_run_does_not_duplicate_sources_or_articles(
    factory, engine, capsys: pytest.CaptureFixture[str]
) -> None:
    feeds = FakeFeeds(items_per_feed=3)
    assert run(factory, feeds) == 0
    capsys.readouterr()

    assert run(factory, feeds) == 0

    assert count(engine, Source) == 4
    assert count(engine, Article) == 12
    out = capsys.readouterr().out
    assert out.count("already present") == 4
    # Nothing new: no 409-like failure, AI processing is skipped with an explanation.
    assert "Skipped: 0 new article(s)" in out
    assert count(engine, AIJob) == 1


def test_existing_source_with_same_feed_url_is_not_added_again(factory, engine) -> None:
    with factory() as db:
        SourceRepository(db).create(SourceCreate(name="My BBC", feed_url=DEMO_URLS[1]))

    assert run(factory, FakeFeeds()) == 0

    assert count(engine, Source) == 4  # My BBC + the three other demo sources
    assert count(engine, Source, Source.name == "BBC Technology") == 0


def test_refresh_skips_sources_and_processes_only_new_articles(
    factory, engine, capsys: pytest.CaptureFixture[str]
) -> None:
    feeds = FakeFeeds(items_per_feed=3)
    assert run(factory, feeds) == 0
    with factory() as db:  # an admin removed one demo source
        db.delete(db.scalar(select(Source).where(Source.name == "The Verge AI")))
        db.commit()
    capsys.readouterr()
    feeds.offset = 3  # the feeds now carry 3 newer stories each

    assert run(factory, feeds, "--refresh") == 0

    out = capsys.readouterr().out
    assert "skipped: --refresh and sources already exist" in out
    assert count(engine, Source) == 3  # not re-added
    assert count(engine, Article) == 9 + 9  # 9 kept (Verge's 3 deleted) + 9 new
    assert count(engine, Article, Article.status == "ai_analyzed") == 18
    assert count(engine, AIJob) == 2


def test_refresh_on_an_empty_database_adds_the_sources(factory, engine) -> None:
    assert run(factory, FakeFeeds(), "--refresh") == 0
    assert count(engine, Source) == 4


def test_one_broken_feed_does_not_fail_the_run(
    factory, engine, capsys: pytest.CaptureFixture[str]
) -> None:
    feeds = FakeFeeds(items_per_feed=3)
    feeds.broken = {DEMO_URLS[0]}

    assert run(factory, feeds) == 0

    out = capsys.readouterr().out
    assert "! MIT Research: failed" in out
    assert "9 new article(s) from 3 of 4 source(s)" in out
    assert count(engine, Article, Article.status == "ai_analyzed") == 9


def test_every_feed_failing_exits_non_zero_and_blames_the_network(
    factory, engine, capsys: pytest.CaptureFixture[str]
) -> None:
    feeds = FakeFeeds()
    feeds.broken = set(DEMO_URLS)

    assert run(factory, feeds) == seed_demo.EXIT_ALL_FEEDS_FAILED != 0

    err = capsys.readouterr().err
    assert "every feed failed" in err
    assert "Internet" in err
    assert count(engine, Source) == 4  # sources stay, so a later run can retry
    assert count(engine, AIJob) == 0


def test_no_active_source_is_an_error(factory, engine) -> None:
    with factory() as db:
        source = SourceRepository(db).create(SourceCreate(name="Off", feed_url=DEMO_URLS[0]))
        SourceRepository(db).set_active(source, False)

    # --refresh keeps the existing (inactive) source and adds none, so nothing can run.
    assert run(factory, FakeFeeds(), "--refresh") == seed_demo.EXIT_SETUP_FAILED


def test_failed_ai_job_exits_non_zero(
    factory, engine, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def broken_process(db: Session, parameters: dict):
        raise RuntimeError("boom")

    monkeypatch.setattr(ai_jobs, "_process", broken_process)

    assert run(factory, FakeFeeds()) == seed_demo.EXIT_SETUP_FAILED

    assert "AI processing failed" in capsys.readouterr().err
    job = Session(engine).scalars(select(AIJob)).one()
    assert job.status == "failed" and job.active_key is None


def test_running_ai_job_is_reported_not_overridden(
    factory, engine, capsys: pytest.CaptureFixture[str]
) -> None:
    from app.repositories.ai_job import AIJobRepository

    with factory() as db:
        AIJobRepository(db).create({}, max_age_seconds=3600)

    assert run(factory, FakeFeeds()) == seed_demo.EXIT_SETUP_FAILED

    assert "Another AI job is running" in capsys.readouterr().err
    assert count(engine, Article, Article.status == "ai_analyzed") == 0


def test_seed_script_has_no_credentials_or_http_calls() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    for forbidden in ("admin_api_token", "X-Admin-Token", "news_api_key", "password", "/api/v1"):
        assert forbidden not in text
