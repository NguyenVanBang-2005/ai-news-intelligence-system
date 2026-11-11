"""Load demo data: add a few public RSS sources, ingest them, then run AI processing.

Runs inside the app's own process (no HTTP, no admin account, no NEWS_API_KEY). It needs
Internet access to read the feeds. Safe to run again: existing sources are kept, known
article URLs are skipped and only articles not processed yet go through AI processing.

Sources: the four RSS feeds of the Docker fresh-stack run of 2026-11-08
(docs/evidence/fresh_stack_startup_cleanup_abd974a.txt, "Ingestion"), where all four
returned articles with status ok.

Sources are created like POST /sources does (SourceCreate + SourceRepository). The feeds
are read by IngestionService like POST /ingestion/run, so the same SSRF checks apply
(app/services/safe_http.py). AI processing creates a job like POST /ai/process does and
runs it here, so it respects the one-active-job lock.

Examples (from the repo root, or inside the API container):
    python scripts/seed_demo.py              # first time: add sources, ingest, process
    python scripts/seed_demo.py --refresh    # demo day: only fetch and process new articles
    docker compose exec api python scripts/seed_demo.py

Exit codes: 0 success; 1 setup problem (no sources, AI unavailable or failed);
2 every feed failed (most likely no Internet access).
"""

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `app` importable

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

import app.db.base  # noqa: E402, F401  (registers all models)
from app.core.config import settings  # noqa: E402
from app.db.session import get_session_factory, session_factory_database_label  # noqa: E402
from app.models.ai_job import AIJob  # noqa: E402
from app.models.article import Article  # noqa: E402
from app.models.source import Source  # noqa: E402
from app.repositories.ai_job import AIJobAlreadyActiveError, AIJobRepository  # noqa: E402
from app.repositories.article import ArticleRepository  # noqa: E402
from app.repositories.source import SourceRepository  # noqa: E402
from app.schemas.ai import AIProcessRequest  # noqa: E402
from app.schemas.source import SourceCreate  # noqa: E402
from app.services.feed import FeedClient  # noqa: E402
from app.services.ingestion import IngestionService  # noqa: E402

# (name, feed URL); see the module docstring for where they come from.
DEMO_SOURCES: tuple[tuple[str, str], ...] = (
    ("MIT Research", "https://news.mit.edu/rss/research"),
    ("BBC Technology", "https://feeds.bbci.co.uk/news/technology/rss.xml"),
    ("TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/"),
    ("The Verge AI", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"),
)

# Upper bound on AI batches per run, so a misbehaving batch can never loop forever.
MAX_AI_BATCHES = 20

EXIT_OK = 0
EXIT_SETUP_FAILED = 1
EXIT_ALL_FEEDS_FAILED = 2

AIRunner = Callable[[sessionmaker[Session]], AIJob]


class SeedError(Exception):
    """A problem that stops the script with EXIT_SETUP_FAILED."""


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Load demo data: add demo RSS sources, ingest them, run AI processing."
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="do not add sources when some already exist; only fetch and process new articles",
    )
    return parser.parse_args(argv)


def add_demo_sources(db: Session) -> int:
    """Add the demo sources missing from the database; returns how many were added.

    A source counts as present when its name or its feed URL is already stored.
    """
    repository = SourceRepository(db)
    added = 0
    for name, url in DEMO_SOURCES:
        payload = SourceCreate(name=name, type="rss", feed_url=url, language="en")
        feed_url = str(payload.feed_url)
        exists = db.scalar(
            select(Source.id).where((Source.name == name) | (Source.feed_url == feed_url))
        )
        if exists is not None:
            print(f"  = {name}: already present")
            continue
        try:
            repository.create(payload)
        except IntegrityError:  # added by someone else meanwhile
            db.rollback()
            print(f"  = {name}: already present")
            continue
        added += 1
        print(f"  + {name}: added ({feed_url})")
    return added


def ingest_active_sources(db: Session, feed_client: FeedClient | None) -> tuple[int, int, int]:
    """Ingest every active source, one at a time; returns (sources, failed, created)."""
    service = IngestionService(db, feed_client=feed_client)
    sources = [(source.id, source.name) for source in SourceRepository(db).list(active_only=True)]
    failed = created = 0
    for source_id, name in sources:
        result = service.run(source_id)
        created += result.articles_created
        if result.errors:
            failed += 1
            # The error names the exception only, never a URL with credentials.
            print(f"  ! {name}: failed ({result.errors[0]})")
        else:
            print(
                f"  - {name}: {result.articles_seen} seen, {result.articles_created} new, "
                f"{result.duplicates_skipped} already stored"
            )
    return len(sources), failed, created


def check_ai_dependencies() -> None:
    """Import the ML stack now, so a missing library is reported before any job exists."""
    try:
        import app.services.topic_model  # noqa: F401
    except (ImportError, OSError) as exc:
        raise SeedError(f"AI libraries could not be loaded ({type(exc).__name__}).") from exc


def run_ai_batch(factory: sessionmaker[Session]) -> AIJob:
    """Create an AI job like POST /ai/process does and run it in this process."""
    from app.services.ai_jobs import run_ai_job

    with factory() as db:
        try:
            job = AIJobRepository(db).create(
                AIProcessRequest().model_dump(),
                max_age_seconds=settings.ai_job_timeout_seconds,
            )
        except AIJobAlreadyActiveError as exc:
            raise SeedError(
                "Another AI job is running (started from the admin page?). "
                "Wait for it to finish, then run this script again."
            ) from exc
        job_id = job.id
    run_ai_job(job_id, factory)
    with factory() as db:
        return AIJobRepository(db).get(job_id)


def unprocessed_count(factory: sessionmaker[Session]) -> int:
    """Articles with text that AI processing has not handled yet (as POST /ai/process)."""
    with factory() as db:
        return ArticleRepository(db).count_for_ai_processing(limit=settings.ai_batch_size)


def process_new_articles(factory: sessionmaker[Session], run_batch: AIRunner) -> int:
    """Run AI batches while enough unprocessed articles remain; returns the batch count."""
    pending = unprocessed_count(factory)
    if pending < settings.ai_min_documents:
        print(
            f"  Skipped: {pending} new article(s) with text; AI processing needs at least "
            f"{settings.ai_min_documents}. Existing topics are kept."
        )
        return 0
    check_ai_dependencies()
    batches = 0
    while pending >= settings.ai_min_documents and batches < MAX_AI_BATCHES:
        print(f"  Processing {pending} article(s); loading the model can take a minute...")
        job = run_batch(factory)
        batches += 1
        if job is None or job.status != "succeeded":
            error = job.error if job is not None else "job not found"
            raise SeedError(f"AI processing failed: {error}")
        result = job.result or {}
        print(
            f"  Done: {result.get('articles_updated', 0)} article(s) updated, "
            f"{result.get('topics_created', 0)} topic(s) created"
        )
        pending = unprocessed_count(factory)
    return batches


def print_totals(factory: sessionmaker[Session]) -> None:
    with factory() as db:
        sources = db.scalar(select(func.count(Source.id))) or 0
        articles = db.scalar(select(func.count(Article.id))) or 0
        processed = (
            db.scalar(select(func.count(Article.id)).where(Article.status == "ai_analyzed")) or 0
        )
    print(f"Totals: {sources} source(s), {articles} article(s), {processed} AI-processed")


def main(
    argv: list[str] | None = None,
    session_factory: sessionmaker[Session] | None = None,
    feed_client: FeedClient | None = None,
    run_batch: AIRunner = run_ai_batch,
) -> int:
    """Run the seed; returns the process exit code (see the module docstring)."""
    args = parse_args(argv)
    factory = session_factory or get_session_factory()
    print(f"Database: {session_factory_database_label(factory)}")

    with factory() as db:
        has_sources = db.scalar(select(func.count(Source.id))) or 0
        if args.refresh and has_sources:
            print("Step 1/3: sources (skipped: --refresh and sources already exist)")
        else:
            print("Step 1/3: demo sources")
            add_demo_sources(db)

        print("Step 2/3: ingestion")
        total, failed, created = ingest_active_sources(db, feed_client)

    if total == 0:
        print("Error: no active source to ingest. Enable a source on the admin page.",
              file=sys.stderr)
        return EXIT_SETUP_FAILED
    print(f"  {created} new article(s) from {total - failed} of {total} source(s)")
    if failed == total:
        print(
            "Error: every feed failed. This is most likely a network problem: check that "
            "the server (or container) can reach the Internet, then run this script again.",
            file=sys.stderr,
        )
        print_totals(factory)
        return EXIT_ALL_FEEDS_FAILED

    print("Step 3/3: AI processing")
    try:
        process_new_articles(factory, run_batch)
    except SeedError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        print_totals(factory)
        return EXIT_SETUP_FAILED

    print_totals(factory)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
