from fastapi import APIRouter, Query

from app.api.deps import DbSession
from app.repositories.article import ArticleRepository
from app.schemas.article import TrendingTopic

router = APIRouter(prefix="/topics", tags=["topics"])


@router.get("/trending", response_model=list[TrendingTopic])
def trending_topics(
    db: DbSession, limit: int = Query(default=10, ge=1, le=50)
) -> list[TrendingTopic]:
    return [
        TrendingTopic(topic=topic, article_count=count)
        for topic, count in ArticleRepository(db).trending(limit)
    ]

