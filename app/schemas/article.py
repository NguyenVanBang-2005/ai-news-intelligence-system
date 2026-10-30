from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class ArticleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_id: int
    # Read from Article.source_name; the repository loads the source with the article.
    source_name: str
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


class TimeseriesPoint(BaseModel):
    # A UTC calendar day, serialized as "YYYY-MM-DD".
    date: date
    # Articles of the topic on that day; 0 when there were none.
    count: int


class TopicTimeseriesRead(BaseModel):
    topic: str
    # Same values as GET /topics/trending: score and count of the recent window.
    trend_score: float
    article_count: int
    # One point per day, oldest first, ending with today (UTC).
    points: list[TimeseriesPoint]

