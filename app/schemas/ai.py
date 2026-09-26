from pydantic import BaseModel, Field

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


class AIProcessResponse(BaseModel):
    documents_received: int
    unique_documents: int
    semantic_duplicates: int
    topics_created: int
    articles_updated: int