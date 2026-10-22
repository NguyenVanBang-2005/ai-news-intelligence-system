from fastapi import APIRouter, Query

from app.api.deps import DbSession
from app.schemas.article import TrendingTopic
from app.services.trending import TrendingTopicsService

router = APIRouter(prefix="/topics", tags=["topics"])


@router.get("/trending", response_model=list[TrendingTopic])
def trending_topics(
    db: DbSession,
    window_hours: int = Query(
        default=24, ge=1, le=168, description="Length of the recent window."
    ),
    baseline_days: int = Query(
        default=7, ge=1, le=30, description="Days before the window that define normal."
    ),
    min_articles: int = Query(
        default=2, ge=1, le=50, description="Fewer recent articles than this never trend."
    ),
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
