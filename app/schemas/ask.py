from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    # A news search request ("EU AI Act fines") or a link to an article.
    input: str = Field(min_length=2, max_length=1500)


class AskSource(BaseModel):
    id: int
    title: str
    url: str
    source_name: str
    published_at: datetime | None
    # Cosine similarity to the request, 0-1.
    similarity: float
    summary: str
    # "ai": written by the LLM. "extractive": first sentences, used when the LLM is unavailable.
    summary_method: Literal["ai", "extractive"]


class AskResponse(BaseModel):
    # Overview with [n] citations into `sources`; null when the LLM is unavailable
    # or nothing relevant was found.
    answer: str | None
    sources: list[AskSource]
