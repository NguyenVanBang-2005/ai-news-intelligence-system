from sqlalchemy.orm import Session

from app.core.config import settings
from app.repositories.article import ArticleRepository
from app.repositories.source import SourceRepository
from app.schemas.ingestion import IngestionResult
from app.services.analyzer import HeuristicAnalyzer
from app.services.feed import FeedClient


class IngestionService:
    def __init__(self, db: Session):
        self.sources = SourceRepository(db)
        self.articles = ArticleRepository(db)
        self.feed_client = FeedClient(settings.request_timeout_seconds)
        self.analyzer = HeuristicAnalyzer()

    def run(self, source_id: int | None = None) -> IngestionResult:
        if source_id is not None:
            source = self.sources.get(source_id)
            sources = [source] if source and source.is_active else []
        else:
            sources = self.sources.list(active_only=True)

        seen = created = duplicates = 0
        errors: list[str] = []
        for source in sources:
            try:
                items = self.feed_client.fetch(source.feed_url, settings.max_feed_items)
                for item in items:
                    seen += 1
                    if self.articles.exists_by_url(item.url):
                        duplicates += 1
                        continue
                    analysis = self.analyzer.analyze(item.title, item.content)
                    self.articles.create(
                        source_id=source.id,
                        title=item.title,
                        url=item.url,
                        author=item.author,
                        content=item.content,
                        summary=analysis.summary,
                        topic=analysis.topic,
                        confidence=analysis.confidence,
                        status="analyzed",
                        published_at=item.published_at,
                    )
                    created += 1
            except Exception as exc:  # one broken source must not stop the batch
                errors.append(f"{source.name}: {type(exc).__name__}: {exc}")
        return IngestionResult(
            sources_processed=len(sources),
            articles_seen=seen,
            articles_created=created,
            duplicates_skipped=duplicates,
            errors=errors,
        )

