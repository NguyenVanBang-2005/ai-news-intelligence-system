from datetime import datetime

import numpy as np
from sqlalchemy import Float, ForeignKey, LargeBinary, String, Text, func
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
    # LLM-written summary, generated on first search hit and reused afterwards.
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    topic: Mapped[str | None] = mapped_column(String(80), index=True, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    # Cached float32 embedding; valid only while embedding_key matches the
    # embedding model and text it was computed for (see cached_embedding).
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    embedding_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())

    source: Mapped["Source"] = relationship(back_populates="articles")  # noqa: F821

    def cached_embedding(self, key: str) -> np.ndarray | None:
        if self.embedding is None or self.embedding_key != key:
            return None
        return np.frombuffer(self.embedding, dtype=np.float32)

    def cache_embedding(self, key: str, vector: np.ndarray) -> None:
        self.embedding = vector.astype(np.float32).tobytes()
        self.embedding_key = key

