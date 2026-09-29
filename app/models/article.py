from datetime import datetime

from sqlalchemy import Float, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.db.types import UTCDateTime


class Article(Base):
    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    title: Mapped[str] = mapped_column(String(500))
    url: Mapped[str] = mapped_column(String(1500), unique=True, index=True)
    author: Mapped[str | None] = mapped_column(String(200), nullable=True)
    content: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    topic: Mapped[str | None] = mapped_column(String(80), index=True, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())

    source: Mapped["Source"] = relationship(back_populates="articles")  # noqa: F821

