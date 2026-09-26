from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.article import Article


class ArticleRepository:
    def __init__(self, db: Session):
        self.db = db

    def exists_by_url(self, url: str) -> bool:
        return self.db.scalar(select(Article.id).where(Article.url == url).limit(1)) is not None

    def create(self, **values: object) -> Article:
        article = Article(**values)
        self.db.add(article)
        self.db.commit()
        self.db.refresh(article)
        return article

    def list(
        self, *, topic: str | None, status: str | None, limit: int, offset: int
    ) -> tuple[list[Article], int]:
        filters = []
        if topic:
            filters.append(Article.topic == topic)
        if status:
            filters.append(Article.status == status)
        total = self.db.scalar(select(func.count(Article.id)).where(*filters)) or 0
        statement = (
            select(Article)
            .where(*filters)
            .order_by(Article.published_at.desc(), Article.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.db.scalars(statement)), total

    def get(self, article_id: int) -> Article | None:
        return self.db.get(Article, article_id)

    def trending(self, limit: int) -> list[tuple[str, int]]:
        statement = (
            select(Article.topic, func.count(Article.id).label("article_count"))
            .where(Article.topic.is_not(None))
            .group_by(Article.topic)
            .order_by(func.count(Article.id).desc())
            .limit(limit)
        )
        return [(topic, count) for topic, count in self.db.execute(statement).all()]

    def list_for_ai_processing(
        self,
        *,
        limit: int,
        force: bool = False,
    ) -> list[Article]:
        filters = [
            Article.content != "",
        ]

        if not force:
            filters.append(Article.status != "ai_analyzed")

        statement = (
            select(Article)
            .where(*filters)
            .order_by(Article.created_at.asc())
            .limit(limit)
        )

        return list(self.db.scalars(statement))

    def save_ai_results(
        self,
        results: list[tuple[int, str, float]],
    ) -> None:
        if not results:
            return

        result_by_id = {
            article_id: (topic, confidence)
            for article_id, topic, confidence in results
        }

        statement = select(Article).where(
            Article.id.in_(result_by_id.keys())
        )

        articles = list(self.db.scalars(statement))

        for article in articles:
            topic, confidence = result_by_id[article.id]

            article.topic = topic
            article.confidence = confidence
            article.status = "ai_analyzed"

        self.db.commit()