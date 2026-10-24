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
    # "ai": written by the LLM. "cached": an LLM summary stored earlier, reused by the
    # public search without calling the LLM. "extractive": first sentences of the article.
    summary_method: Literal["ai", "cached", "extractive"]


class AiSearchRequest(BaseModel):
    # Search words only; links are refused (reading a link needs /ai/ask).
    input: str = Field(min_length=2, max_length=500)


class AiSearchResponse(BaseModel):
    # Stored articles only, with extractive summaries; no LLM answer.
    sources: list[AskSource]


class AskResponse(BaseModel):
    # Overview with [n] citations into `sources`; null when the LLM is unavailable
    # or nothing relevant was found.
    answer: str | None
    sources: list[AskSource]
