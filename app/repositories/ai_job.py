import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ai_job import AIJob

ACTIVE_STATUSES = ("pending", "running")


class AIJobRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, parameters: dict) -> AIJob:
        job = AIJob(id=str(uuid.uuid4()), parameters=parameters)
        self.db.add(job)
        self.db.commit()
        return job

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
        job.result = result
        job.finished_at = datetime.now(UTC)
        self.db.commit()

    def mark_failed(self, job: AIJob, error: str) -> None:
        job.status = "failed"
        job.error = error
        job.finished_at = datetime.now(UTC)
        self.db.commit()
