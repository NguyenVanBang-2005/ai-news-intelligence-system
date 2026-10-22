from datetime import datetime

from sqlalchemy import JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.db.types import UTCDateTime


class Topic(Base):
    """A topic seen in earlier batches, kept so later batches reuse its label."""

    __tablename__ = "topics"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(80), index=True)
    # Unit-length mean embedding of the articles assigned to this topic so far.
    centroid: Mapped[list[float]] = mapped_column(JSON)
    article_count: Mapped[int] = mapped_column(default=0)
    # Top words of the latest batch that reached this topic: [{"word": ..., "weight": ...}].
    keywords: Mapped[list[dict]] = mapped_column(JSON, default=list)
    # Articles of the latest batch closest to the centroid, best first.
    representative_article_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())
