import logging
from dataclasses import replace

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.source import SOURCE_TYPE_NEWS_API
from app.repositories.article import ArticleRepository, DuplicateArticleError
from app.repositories.source import SourceRepository
from app.schemas.ingestion import IngestionResult
from app.services.analyzer import HeuristicAnalyzer
from app.services.content_extractor import ArticleContentExtractor
from app.services.feed import FeedClient, FeedItem
from app.services.news_api import GNewsClient
from app.services.text_cleaning import truncate

logger = logging.getLogger(__name__)

# Article.status values set during ingestion.
STATUS_ANALYZED = "analyzed"
STATUS_MISSING_CONTENT = "missing_content"


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
        if source_id is not None:
            source = self.sources.get(source_id)
            sources = [source] if source else []
        else:
            sources = self.sources.list(active_only=True)

        seen = created = duplicates = processed = 0
        errors: list[str] = []
        for position, source in enumerate(sources, start=1):
            # The label is independent of the ORM so the error handler never touches it;
            # it upgrades to the real name once that has been read successfully.
            label = f"source #{position}"
            processed += 1
            try:
                # Read every ORM attribute up front: a rollback expires the objects, and
                # any of these reads can fail (detached instance, dropped connection).
                label = source.name
                if not source.is_active:
                    processed -= 1
                    continue
                source_pk = source.id
                items = self._fetch_items(
                    source_type=source.type,
                    feed_url=source.feed_url,
                    query=source.query,
                    language=source.language,
                )
                for item in items:
                    seen += 1
                    if self.articles.exists_by_url(item.url):
                        duplicates += 1
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
                        duplicates += 1
                        continue
                    created += 1
            except Exception as exc:  # one broken source must not stop the batch
                self._rollback_quietly()
                errors.append(f"{label}: {type(exc).__name__}: {exc}")
        return IngestionResult(
            sources_processed=processed,
            articles_seen=seen,
            articles_created=created,
            duplicates_skipped=duplicates,
            errors=errors,
        )

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
