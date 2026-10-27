import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.ai_job import AIJob

ACTIVE_STATUSES = ("pending", "running")
ACTIVE_KEY = "ai_process"


class AIJobAlreadyActiveError(Exception):
    """Another AI job is pending or running."""


class AIJobRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, parameters: dict, *, max_age_seconds: int) -> AIJob:
        """Create the one active job, or raise AIJobAlreadyActiveError if one exists.

        Jobs older than max_age_seconds are failed first, in the same transaction.
        """
        self._fail_timed_out_jobs(max_age_seconds)
        job = AIJob(id=str(uuid.uuid4()), parameters=parameters, active_key=ACTIVE_KEY)
        self.db.add(job)
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise AIJobAlreadyActiveError from exc
        return job

    def _fail_timed_out_jobs(self, max_age_seconds: int) -> None:
        """Mark dead jobs failed and free their active_key (committed with the new job)."""
        oldest = datetime.now(UTC) - timedelta(seconds=max_age_seconds)
        self.db.execute(
            update(AIJob)
            .where(AIJob.active_key.is_not(None), AIJob.created_at < oldest)
            .values(
                status="failed",
                error="AI job timed out.",
                finished_at=datetime.now(UTC),
                active_key=None,
            )
        )

    def get(self, job_id: str) -> AIJob | None:
        return self.db.get(AIJob, job_id)

    def find_active(self, *, max_age_seconds: int) -> AIJob | None:
        """A job that is still pending or running. Older ones are assumed dead."""
        oldest = datetime.now(UTC) - timedelta(seconds=max_age_seconds)
        statement = (
            select(AIJob)
            .where(AIJob.status.in_(ACTIVE_STATUSES), AIJob.created_at >= oldest)
            .order_by(AIJob.created_at)
            .limit(1)
        )
        return self.db.scalar(statement)

    def mark_running(self, job: AIJob) -> None:
        job.status = "running"
        job.started_at = datetime.now(UTC)
        self.db.commit()

    def mark_succeeded(self, job: AIJob, result: dict) -> None:
        job.status = "succeeded"
        job.active_key = None
        job.result = result
        job.finished_at = datetime.now(UTC)
        self.db.commit()

    def mark_failed(self, job: AIJob, error: str) -> None:
        job.status = "failed"
        job.active_key = None
        job.error = error
        job.finished_at = datetime.now(UTC)
        self.db.commit()

    def release_active_key(self, job_id: str, error: str) -> None:
        """Last resort: fail the job if still active and free its active_key."""
        self.db.execute(
            update(AIJob)
            .where(AIJob.id == job_id, AIJob.active_key.is_not(None))
            .values(
                status="failed",
                error=error,
                finished_at=datetime.now(UTC),
                active_key=None,
            )
        )
        self.db.commit()
