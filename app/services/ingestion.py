import logging
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.source import (
    SOURCE_TYPE_NEWS_API,
    SYNC_STATUS_ERROR,
    SYNC_STATUS_OK,
    SYNC_STATUS_WARNING,
    Source,
)
from app.repositories.article import ArticleRepository, DuplicateArticleError
from app.repositories.source import SourceRepository
from app.schemas.ingestion import IngestionResult
from app.services.analyzer import HeuristicAnalyzer
from app.services.content_extractor import ArticleContentExtractor
from app.services.feed import FeedClient, FeedItem
from app.services.news_api import GNewsClient
from app.services.sync_errors import short_error_message
from app.services.text_cleaning import truncate

logger = logging.getLogger(__name__)

# Article.status values set during ingestion.
STATUS_ANALYZED = "analyzed"
STATUS_MISSING_CONTENT = "missing_content"


@dataclass
class IngestionTotals:
    """Running counts of one ingestion batch, over all its sources."""

    processed: int = 0
    seen: int = 0
    created: int = 0
    duplicates: int = 0
    errors: list[str] = field(default_factory=list)


class IngestionService:
    def __init__(
        self,
        db: Session,
        feed_client: FeedClient | None = None,
        news_client: GNewsClient | None = None,
        extractor: ArticleContentExtractor | None = None,
    ):
        self.db = db
        self.sources = SourceRepository(db)
        self.articles = ArticleRepository(db)
        self.feed_client = feed_client or FeedClient(settings.request_timeout_seconds)
        self.news_client = news_client or GNewsClient.from_settings()
        self.extractor = extractor or self._default_extractor()
        self.analyzer = HeuristicAnalyzer()

    @staticmethod
    def _default_extractor() -> ArticleContentExtractor | None:
        """Full-text extraction downloads article pages; None switches it off."""
        if not settings.ingestion_full_text:
            return None
        return ArticleContentExtractor(
            timeout_seconds=settings.request_timeout_seconds,
            max_download_bytes=settings.article_max_download_bytes,
            max_redirects=settings.article_max_redirects,
        )

    def _rollback_quietly(self) -> None:
        try:
            self.db.rollback()
        except Exception:  # never let cleanup mask the source error
            pass

    def run(self, source_id: int | None = None) -> IngestionResult:
        """Ingest one source (source_id) or every active source; inactive ones are skipped."""
        totals = IngestionTotals()
        for position, source in enumerate(self._sources_to_run(source_id), start=1):
            self._run_source(source, position, totals)
        return IngestionResult(
            sources_processed=totals.processed,
            articles_seen=totals.seen,
            articles_created=totals.created,
            duplicates_skipped=totals.duplicates,
            errors=totals.errors,
        )

    def _sources_to_run(self, source_id: int | None) -> list:
        """The requested source (if it exists), or all active sources."""
        if source_id is None:
            return self.sources.list(active_only=True)
        source = self.sources.get(source_id)
        return [source] if source else []

    def _run_source(self, source, position: int, totals: IngestionTotals) -> None:
        """Ingest one source and record its sync status; a failure never escapes."""
        # The label is independent of the ORM so the error handler never touches it;
        # it upgrades to the real name once that has been read successfully.
        label = f"source #{position}"
        source_pk: int | None = None
        totals.processed += 1
        seen_before = totals.seen
        try:
            # Read every ORM attribute up front: a rollback expires the objects, and
            # any of these reads can fail (detached instance, dropped connection).
            label = source.name
            if not source.is_active:
                totals.processed -= 1
                return  # an inactive source is not touched, not even its status
            source_pk = source.id
            items = self._fetch_items(
                source_type=source.type,
                feed_url=source.feed_url,
                query=source.query,
                language=source.language,
            )
            self._store_items(source_pk, items, totals)
        except Exception as exc:  # one broken source must not stop the batch
            self._rollback_quietly()
            totals.errors.append(f"{label}: {type(exc).__name__}: {exc}")
            if source_pk is not None:
                self._record_sync(source_pk, SYNC_STATUS_ERROR, short_error_message(exc))
            return
        status = SYNC_STATUS_OK if totals.seen > seen_before else SYNC_STATUS_WARNING
        self._record_sync(source_pk, status, None)

    def _store_items(
        self, source_pk: int, items: list[FeedItem], totals: IngestionTotals
    ) -> None:
        """Save the items that are not stored yet, counting them in totals as it goes."""
        for item in items:
            totals.seen += 1
            if self.articles.exists_by_url(item.url):
                totals.duplicates += 1
                continue
            item = self._with_full_text(item)
            # Title-only items still get a baseline topic, but are flagged so the
            # summarization step can skip them (it only reads non-empty content).
            analysis = self.analyzer.analyze(item.title, item.content)
            try:
                self.articles.create(
                    source_id=source_pk,
                    title=item.title,
                    url=item.url,
                    author=item.author,
                    content=item.content,
                    summary=analysis.summary,
                    topic=analysis.topic,
                    confidence=analysis.confidence,
                    status=STATUS_ANALYZED if item.content else STATUS_MISSING_CONTENT,
                    published_at=item.published_at,
                )
            except DuplicateArticleError:  # inserted elsewhere after the exists check
                totals.duplicates += 1
                continue
            totals.created += 1

    def _record_sync(self, source_pk: int, status: str, error: str | None) -> None:
        """Commit the source's sync outcome; a failure here is logged, never raised."""
        try:
            self.db.execute(
                update(Source)
                .where(Source.id == source_pk)
                .values(last_synced_at=datetime.now(UTC), last_status=status, last_error=error)
            )
            self.db.commit()
        except Exception:
            logger.warning("Could not record sync status of source %s", source_pk, exc_info=True)
            self._rollback_quietly()

    def _fetch_items(
        self,
        *,
        source_type: str,
        feed_url: str | None,
        query: str | None,
        language: str,
    ) -> list[FeedItem]:
        """The source's current articles, from its feed or from the news API."""

        if source_type == SOURCE_TYPE_NEWS_API:
            return self.news_client.search(
                query,
                language=language,
                max_items=min(settings.max_feed_items, settings.news_api_max_articles),
            )

        return self.feed_client.fetch(feed_url, settings.max_feed_items)

    def _with_full_text(self, item: FeedItem) -> FeedItem:
        """Download the article page when the source only gave a short snippet.

        Keeps the snippet when extraction is off, fails, or finds less text.
        """

        if self.extractor is None or len(item.content) >= settings.full_text_min_chars:
            return item

        try:
            page_text = self.extractor.extract_from_url(item.url)
        except Exception:  # a bad page must not cost the rest of the source
            logger.warning("Full-text extraction failed for %s", item.url, exc_info=True)
            return item

        if not page_text or len(page_text) <= len(item.content):
            return item

        return replace(
            item,
            content=truncate(page_text.strip(), settings.max_article_content_chars),
        )
