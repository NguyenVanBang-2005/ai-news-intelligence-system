from sqlalchemy.orm import Session

from app.core.config import settings
from app.repositories.article import ArticleRepository, DuplicateArticleError
from app.repositories.source import SourceRepository
from app.schemas.ingestion import IngestionResult
from app.services.analyzer import HeuristicAnalyzer
from app.services.feed import FeedClient

# Article.status values set during ingestion.
STATUS_ANALYZED = "analyzed"
STATUS_MISSING_CONTENT = "missing_content"


class IngestionService:
    def __init__(self, db: Session, feed_client: FeedClient | None = None):
        self.db = db
        self.sources = SourceRepository(db)
        self.articles = ArticleRepository(db)
        self.feed_client = feed_client or FeedClient(settings.request_timeout_seconds)
        self.analyzer = HeuristicAnalyzer()

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
                source_pk, feed_url = source.id, source.feed_url
                items = self.feed_client.fetch(feed_url, settings.max_feed_items)
                for item in items:
                    seen += 1
                    if self.articles.exists_by_url(item.url):
                        duplicates += 1
                        continue
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

