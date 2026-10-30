from datetime import datetime

from sqlalchemy import Boolean, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.db.types import UTCDateTime

# Where a source's articles come from.
SOURCE_TYPE_RSS = "rss"            # an RSS/Atom feed at feed_url
SOURCE_TYPE_NEWS_API = "news_api"  # a news search API, searched for `query`

# Outcome of a source's latest sync (Source.last_status); NULL until it is first synced.
SYNC_STATUS_OK = "ok"            # fetched without error and saw at least one article
SYNC_STATUS_WARNING = "warning"  # fetched without error but saw no articles
SYNC_STATUS_ERROR = "error"      # fetching or parsing failed; see Source.last_error

# Source.last_error is public (GET /sources), so it holds only a short fixed message.
LAST_ERROR_MAX_CHARS = 300


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    type: Mapped[str] = mapped_column(
        String(20), default=SOURCE_TYPE_RSS, server_default=SOURCE_TYPE_RSS
    )
    # Set for RSS sources only.
    feed_url: Mapped[str | None] = mapped_column(String(1000), unique=True, nullable=True)
    # Set for news API sources only: the search keywords.
    query: Mapped[str | None] = mapped_column(String(200), nullable=True)
    language: Mapped[str] = mapped_column(String(10), default="en")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())
    # Latest ingestion of this source: when it ended, its SYNC_STATUS_* and, on error, a
    # sanitized message (see app/services/sync_errors.py). All NULL before the first sync.
    last_synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(10), nullable=True)
    last_error: Mapped[str | None] = mapped_column(
        String(LAST_ERROR_MAX_CHARS), nullable=True
    )

    articles: Mapped[list["Article"]] = relationship(  # noqa: F821
        back_populates="source", cascade="all, delete-orphan"
    )
