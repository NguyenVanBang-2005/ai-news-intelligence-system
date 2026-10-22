from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import settings


class AIProcessRequest(BaseModel):
    limit: int = Field(
        default=settings.ai_batch_size,
        ge=settings.ai_min_documents,
        le=5000,
    )

    duplicate_threshold: float = Field(
        default=settings.duplicate_similarity_threshold,
        ge=0.70,
        le=1.0,
    )

    force: bool = False


class AIProcessResult(BaseModel):
    documents_received: int
    unique_documents: int
    semantic_duplicates: int
    topics_created: int
    articles_updated: int
    # "hdbscan_soft": confidence comes from HDBSCAN's soft clustering.
    # "fallback": no usable probabilities, every confidence is a flat default.
    confidence_method: Literal["hdbscan_soft", "fallback"]
    # Average NPMI of the topics' top words, -1 to 1 (higher is better). Compare
    # between batches to judge tuning changes; null when there was nothing to measure.
    topic_coherence: float | None


class AIJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: Literal["pending", "running", "succeeded", "failed"]
    result: AIProcessResult | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class TopicKeyword(BaseModel):
    word: str
    weight: float


class RepresentativeArticle(BaseModel):
    id: int
    title: str
    url: str


class TopicRead(BaseModel):
    id: int
    label: str
    # Articles currently labelled with this topic.
    size: int
    keywords: list[TopicKeyword]
    representative_articles: list[RepresentativeArticle]
    updated_at: datetime
