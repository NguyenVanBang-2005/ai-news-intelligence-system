from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ArticleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_id: int
    title: str
    url: str
    author: str | None
    content: str
    summary: str | None
    topic: str | None
    confidence: float | None
    status: str
    published_at: datetime | None
    created_at: datetime


class ArticlePage(BaseModel):
    items: list[ArticleRead]
    total: int
    limit: int
    offset: int


class TrendingTopic(BaseModel):
    topic: str
    # Articles about this topic in the recent window.
    article_count: int
    # Articles a window of that length normally has, from the baseline days before it.
    expected_count: float
    # Standard deviations above normal; higher means a stronger burst.
    trend_score: float

