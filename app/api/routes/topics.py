from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import DbSession
from app.schemas.article import TimeseriesPoint, TopicTimeseriesRead, TrendingTopic
from app.services.topic_timeseries import TopicTimeseriesService
from app.services.trending import TrendingTopicsService

router = APIRouter(prefix="/topics", tags=["topics"])

# Parameters that pick trending topics; shared so both endpoints choose topics alike.
WindowHours = Annotated[
    int, Query(ge=1, le=168, description="Length of the recent window.")
]
BaselineDays = Annotated[
    int, Query(ge=1, le=30, description="Days before the window that define normal.")
]
MinArticles = Annotated[
    int, Query(ge=1, le=50, description="Fewer recent articles than this never trend.")
]


@router.get("/trending", response_model=list[TrendingTopic])
def trending_topics(
    db: DbSession,
    window_hours: WindowHours = 24,
    baseline_days: BaselineDays = 7,
    min_articles: MinArticles = 2,
    limit: int = Query(default=10, ge=1, le=50),
) -> list[TrendingTopic]:
    """Topics with clearly more articles in the recent window than usual,
    strongest burst first."""

    trending = TrendingTopicsService(db).find(
        window_hours=window_hours,
        baseline_days=baseline_days,
        min_articles=min_articles,
        limit=limit,
    )

    return [
        TrendingTopic(
            topic=item.topic,
            article_count=item.recent_count,
            expected_count=item.expected_count,
            trend_score=item.trend_score,
        )
        for item in trending
    ]


@router.get("/timeseries", response_model=list[TopicTimeseriesRead])
def topic_timeseries(
    db: DbSession,
    days: int = Query(default=7, ge=1, le=30, description="UTC days, ending today."),
    limit: int = Query(default=3, ge=1, le=10, description="Topics to return."),
    window_hours: WindowHours = 24,
    baseline_days: BaselineDays = 7,
    min_articles: MinArticles = 2,
) -> list[TopicTimeseriesRead]:
    """Daily article counts (UTC days, zero-filled) for the strongest trending topics."""

    series = TopicTimeseriesService(db).find(
        days=days,
        limit=limit,
        window_hours=window_hours,
        baseline_days=baseline_days,
        min_articles=min_articles,
    )

    return [
        TopicTimeseriesRead(
            topic=item.topic,
            trend_score=item.trend_score,
            article_count=item.article_count,
            points=[TimeseriesPoint(date=p.date, count=p.count) for p in item.points],
        )
        for item in series
    ]
