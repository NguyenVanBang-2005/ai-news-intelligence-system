from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class SourceCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    type: Literal["rss", "news_api"] = Field(
        default="rss",
        description="rss: an RSS/Atom feed. news_api: a news search for `query`.",
    )
    feed_url: HttpUrl | None = Field(
        default=None,
        description=(
            "RSS sources only. Public RSS/Atom feed URL; HTML topic pages and article "
            "pages are unsupported."
        ),
    )
    query: str | None = Field(
        default=None,
        min_length=2,
        max_length=200,
        description="news_api sources only. Search keywords, e.g. 'toyota electric'.",
    )
    language: str = Field(default="en", min_length=2, max_length=10)

    @model_validator(mode="after")
    def check_fields_for_type(self) -> "SourceCreate":
        if self.type == "rss":
            if self.feed_url is None:
                raise ValueError("RSS sources need a feed_url")
            if self.query is not None:
                raise ValueError("RSS sources do not take a query")

        if self.type == "news_api":
            if self.query is None:
                raise ValueError("news_api sources need a query")
            if self.feed_url is not None:
                raise ValueError("news_api sources do not take a feed_url")

        return self


class SourceUpdate(BaseModel):
    """Fields an admin may change on a saved source."""

    is_active: bool


class SourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    type: str
    feed_url: str | None
    query: str | None
    language: str
    is_active: bool
    created_at: datetime
    # Latest sync; all null until the source is first ingested. last_status is "ok",
    # "warning" (no articles seen) or "error"; last_error is a short fixed message only.
    last_synced_at: datetime | None
    last_status: Literal["ok", "warning", "error"] | None
    last_error: str | None
