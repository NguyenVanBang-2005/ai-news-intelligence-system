from datetime import UTC, datetime

from sqlalchemy import JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.db.types import UTCDateTime


def _now() -> datetime:
    return datetime.now(UTC)


class AIJob(Base):
    """One run of the AI pipeline, so clients can poll for its outcome."""

    __tablename__ = "ai_jobs"
    __table_args__ = (UniqueConstraint("active_key", name="uq_ai_jobs_active_key"),)

    # status: pending -> running -> succeeded | failed
    # active_key is "ai_process" while the job is pending/running and NULL afterwards,
    # so the unique constraint lets the database allow only one active job.
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), index=True, default="pending")
    active_key: Mapped[str | None] = mapped_column(String(30), nullable=True)
    parameters: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
