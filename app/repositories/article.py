from __future__ import annotations

from datetime import datetime

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.article import Article


class DuplicateArticleError(Exception):
    """The article URL already exists (e.g. inserted concurrently after an exists check)."""


# Name of the unique index SQLAlchemy creates for Article.url (unique=True, index=True).
_URL_UNIQUE_CONSTRAINTS = {"ix_articles_url"}


def is_url_unique_violation(exc: IntegrityError) -> bool:
    """True only when the driver reports a unique violation on articles.url.

    Unknown or unrecognized errors return False so the caller re-raises them.
    """
    orig = exc.orig
    # SQLite: "UNIQUE constraint failed: articles.url" (exactly this one column).
    if str(orig).strip() == "UNIQUE constraint failed: articles.url":
        return True
    # PostgreSQL (psycopg2/psycopg): SQLSTATE 23505 plus the violated index name.
    if getattr(orig, "pgcode", None) == "23505" or getattr(orig, "sqlstate", None) == "23505":
        diag = getattr(orig, "diag", None)
        return getattr(diag, "constraint_name", None) in _URL_UNIQUE_CONSTRAINTS
    return False


class ArticleRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_url(self, url: str) -> Article | None:
        return self.db.scalar(select(Article).where(Article.url == url).limit(1))

    def exists_by_url(self, url: str) -> bool:
        return self.db.scalar(select(Article.id).where(Article.url == url).limit(1)) is not None

    def create(self, **values: object) -> Article:
        article = Article(**values)
        self.db.add(article)
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            # Only a unique violation on articles.url is a duplicate; anything else is re-raised.
            if is_url_unique_violation(exc):
                raise DuplicateArticleError(str(values["url"])) from exc
            raise
        except Exception:
            self.db.rollback()
            raise
        # No refresh: the row is already committed, and a failing refresh must not make the
        # caller believe the insert failed. Attributes reload lazily if the session expires them.
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
            .order_by(Article.published_at.desc().nulls_last(), Article.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.db.scalars(statement)), total

    def get(self, article_id: int) -> Article | None:
        return self.db.get(Article, article_id)

    def get_many(self, article_ids: set[int]) -> list[Article]:
        if not article_ids:
            return []
        return list(self.db.scalars(select(Article).where(Article.id.in_(article_ids))))

    def topic_counts(
        self,
        *,
        baseline_start: datetime,
        window_start: datetime,
        end: datetime,
    ) -> list[tuple[str, int, int]]:
        """Per topic: (topic, articles in [window_start, end], articles in
        [baseline_start, window_start)).

        An article's time is when it was published, or when it was collected
        if the feed gave no date.
        """
        article_time = func.coalesce(Article.published_at, Article.created_at)
        in_window = article_time >= window_start

        statement = (
            select(
                Article.topic,
                func.count(Article.id).filter(in_window),
                func.count(Article.id).filter(~in_window),
            )
            .where(
                Article.topic.is_not(None),
                article_time >= baseline_start,
                article_time <= end,
            )
            .group_by(Article.topic)
        )

        return [
            (topic, recent_count, baseline_count)
            for topic, recent_count, baseline_count in self.db.execute(statement).all()
        ]

    @staticmethod
    def _ai_processing_filters(*, force: bool) -> list:
        filters = [
            Article.content != "",
        ]

        if not force:
            filters.append(Article.status != "ai_analyzed")

        return filters

    def count_for_ai_processing(self, *, limit: int, force: bool = False) -> int:
        """How many articles list_for_ai_processing would return, without loading them."""
        total = self.db.scalar(
            select(func.count(Article.id)).where(*self._ai_processing_filters(force=force))
        )
        return min(total or 0, limit)

    def list_for_ai_processing(
        self,
        *,
        limit: int,
        force: bool = False,
    ) -> list[Article]:
        statement = (
            select(Article)
            .where(*self._ai_processing_filters(force=force))
            .order_by(Article.created_at.asc())
            .limit(limit)
        )

        return list(self.db.scalars(statement))

    def list_for_search(self, *, limit: int) -> list[Article]:
        """The newest articles that have content to search in."""
        statement = (
            select(Article)
            .where(Article.content != "")
            .order_by(Article.created_at.desc(), Article.id.desc())
            .limit(limit)
        )
        return list(self.db.scalars(statement))

    def save_content(self, article: Article, content: str) -> None:
        article.content = content
        article.status = "analyzed"
        self.db.commit()

    def save_ai_summary(self, article: Article, summary: str) -> None:
        article.ai_summary = summary
        self.db.commit()

    def save_embeddings(self, entries: list[tuple[Article, str, np.ndarray]]) -> None:
        for article, key, vector in entries:
            article.cache_embedding(key, vector)

        self.db.commit()

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
