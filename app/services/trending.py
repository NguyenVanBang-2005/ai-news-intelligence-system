"""Trending topics: topics with clearly more articles right now than usual.

For every topic we count:
  - recent:   articles in the last `window_hours`
  - baseline: articles in the `baseline_days` before that window

The baseline tells how many articles a window normally has (`expected`). The trend score
is how far `recent` is above that, measured in standard deviations of a Poisson count:

    trend_score = (recent - expected) / sqrt(expected + 1)

So 3 new articles on a quiet topic beat 30 articles on a topic that always has 30, and a
topic that is busy but not busier than usual is not trending at all.
"""

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.repositories.article import ArticleRepository

# Catch-all labels say nothing about what is happening, so they never trend.
# They must match the labels written by the analyzer and the topic model.
CATCH_ALL_TOPICS = {"Other", "Other / Outlier"}


@dataclass(frozen=True)
class TrendingTopic:
    topic: str
    recent_count: int
    expected_count: float
    trend_score: float


def trend_score(recent_count: int, expected_count: float) -> float:
    """Standard deviations above normal; the +1 keeps brand-new topics finite."""
    return (recent_count - expected_count) / math.sqrt(expected_count + 1)


class TrendingTopicsService:
    def __init__(self, db: Session):
        self.articles = ArticleRepository(db)

    def find(
        self,
        *,
        window_hours: int,
        baseline_days: int,
        min_articles: int,
        limit: int,
    ) -> list[TrendingTopic]:
        """Topics with at least `min_articles` recent articles that are above normal,
        highest trend score first."""

        now = datetime.now(UTC)
        window_start = now - timedelta(hours=window_hours)
        baseline_start = window_start - timedelta(days=baseline_days)

        # How many windows fit in the baseline period, to turn its count into a
        # "normal" count for one window.
        windows_in_baseline = baseline_days * 24 / window_hours

        trending: list[TrendingTopic] = []

        for topic, recent_count, baseline_count in self.articles.topic_counts(
            baseline_start=baseline_start,
            window_start=window_start,
            end=now,
        ):
            if topic in CATCH_ALL_TOPICS or recent_count < min_articles:
                continue

            expected_count = baseline_count / windows_in_baseline
            score = trend_score(recent_count, expected_count)

            if score <= 0:
                continue  # not busier than usual

            trending.append(
                TrendingTopic(
                    topic=topic,
                    recent_count=recent_count,
                    expected_count=round(expected_count, 2),
                    trend_score=round(score, 2),
                )
            )

        trending.sort(key=lambda item: (item.trend_score, item.recent_count), reverse=True)

        return trending[:limit]
