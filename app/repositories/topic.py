from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.article import Article
from app.models.topic import Topic


class TopicRepository:
    """Never commits: the caller's commit saves topics together with the article results."""

    def __init__(self, db: Session):
        self.db = db

    def list_all(self) -> list[Topic]:
        return list(self.db.scalars(select(Topic).order_by(Topic.id)))

    def list_with_sizes(self) -> list[tuple[Topic, int]]:
        """Topics with their current number of articles, largest first."""
        size = func.count(Article.id)
        statement = (
            select(Topic, size)
            .outerjoin(Article, Article.topic == Topic.label)
            .group_by(Topic.id)
            .order_by(size.desc(), Topic.id)
        )
        return [(topic, count) for topic, count in self.db.execute(statement).all()]

    def add(
        self,
        *,
        label: str,
        centroid: list[float],
        article_count: int,
        keywords: list[dict],
        representative_article_ids: list[int],
    ) -> None:
        self.db.add(
            Topic(
                label=label,
                centroid=centroid,
                article_count=article_count,
                keywords=keywords,
                representative_article_ids=representative_article_ids,
            )
        )

    def update(
        self,
        topic: Topic,
        *,
        centroid: list[float],
        article_count: int,
        keywords: list[dict],
        representative_article_ids: list[int],
    ) -> None:
        topic.centroid = centroid
        topic.article_count = article_count
        topic.keywords = keywords
        topic.representative_article_ids = representative_article_ids
        topic.updated_at = datetime.now(UTC)
