from datetime import datetime

from sqlalchemy import Boolean, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.db.types import UTCDateTime

# Where a source's articles come from.
SOURCE_TYPE_RSS = "rss"            # an RSS/Atom feed at feed_url
SOURCE_TYPE_NEWS_API = "news_api"  # a news search API, searched for `query`


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

    articles: Mapped[list["Article"]] = relationship(  # noqa: F821
        back_populates="source", cascade="all, delete-orphan"
    )
