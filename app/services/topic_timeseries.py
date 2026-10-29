"""Daily article counts for the top trending topics, for the trends chart.

Topics are picked by TrendingTopicsService (same trend score, same catch-all labels left
out). Days are UTC calendar days; an article's time is coalesce(published_at, created_at).
Counting per day happens in Python, so the result is the same on SQLite and PostgreSQL.
"""

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy.orm import Session

from app.repositories.article import ArticleRepository
from app.services.trending import TrendingTopicsService

# Most (topic, time) rows read per request; past it the oldest days are undercounted.
TIMESERIES_MAX_ROWS = 50_000


@dataclass(frozen=True)
class DailyCount:
    date: date
    count: int


@dataclass(frozen=True)
class TopicTimeseries:
    topic: str
    trend_score: float
    article_count: int
    points: list[DailyCount]


def utc_days_ending_today(days: int, now: datetime) -> list[date]:
    """The `days` consecutive UTC dates that end with today's UTC date, oldest first."""
    today = now.astimezone(UTC).date()
    return [today - timedelta(days=offset) for offset in range(days - 1, -1, -1)]


def start_of_utc_day(day: date) -> datetime:
    """Midnight UTC at the start of `day`."""
    return datetime.combine(day, time.min, tzinfo=UTC)


class TopicTimeseriesService:
    def __init__(self, db: Session):
        self.articles = ArticleRepository(db)
        self.trending = TrendingTopicsService(db)

    def find(
        self,
        *,
        days: int,
        limit: int,
        window_hours: int,
        baseline_days: int,
        min_articles: int,
    ) -> list[TopicTimeseries]:
        """The `limit` strongest trending topics, each with one count per UTC day."""
        topics = self.trending.find(
            window_hours=window_hours,
            baseline_days=baseline_days,
            min_articles=min_articles,
            limit=limit,
        )
        if not topics:
            return []
        day_list = utc_days_ending_today(days, datetime.now(UTC))
        counts = self._count_per_topic_and_day([item.topic for item in topics], day_list)
        return [
            TopicTimeseries(
                topic=item.topic,
                trend_score=item.trend_score,
                article_count=item.recent_count,
                points=[DailyCount(day, counts[(item.topic, day)]) for day in day_list],
            )
            for item in topics
        ]

    def _count_per_topic_and_day(
        self, topics: list[str], day_list: list[date]
    ) -> Counter[tuple[str, date]]:
        """Articles per (topic, UTC date) over day_list, read with a single query."""
        rows = self.articles.topic_timestamps(
            topics=topics,
            start=start_of_utc_day(day_list[0]),
            end=start_of_utc_day(day_list[-1] + timedelta(days=1)),
            max_rows=TIMESERIES_MAX_ROWS,
        )
        return Counter((topic, moment.astimezone(UTC).date()) for topic, moment in rows)
