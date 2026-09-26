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
    article_count: int

