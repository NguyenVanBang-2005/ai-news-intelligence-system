"""Runs the AI pipeline in the background. No ML libraries are imported at module level."""

import logging
from dataclasses import asdict

from sqlalchemy.orm import Session, sessionmaker

from app.repositories.ai_job import AIJobRepository
from app.services.ai_errors import (
    MODEL_UNAVAILABLE_MESSAGE,
    PROCESSING_FAILED_MESSAGE,
    EmbeddingModelUnavailableError,
    NotEnoughDocumentsError,
)

logger = logging.getLogger(__name__)

INTERRUPTED_BY_RESTART_MESSAGE = "Interrupted by application restart"


def fail_interrupted_jobs(session_factory: sessionmaker[Session]) -> None:
    """Mark jobs left pending or running by a previous run of the app as failed.

    Jobs run inside the API process, so at startup none of them can still be alive. This
    holds only with ONE worker process (the system's current assumption): with several
    workers, a starting worker would fail jobs that another worker is still running.
    Database errors (no connection, no ai_jobs table yet) are logged, never raised.
    """
    try:
        with session_factory() as db:
            count = AIJobRepository(db).fail_all_active(INTERRUPTED_BY_RESTART_MESSAGE)
    except Exception:
        logger.warning("Could not fail interrupted AI jobs at startup", exc_info=True)
        return
    if count:
        logger.warning("Marked %d interrupted AI job(s) as failed", count)


def run_ai_job(job_id: str, session_factory: sessionmaker[Session]) -> None:
    """Process the articles of one job and record the outcome on the job.

    Runs after the HTTP response was sent, so it opens its own database session and
    must never raise: every failure ends up as the job's error message.
    """

    with session_factory() as db:
        jobs = AIJobRepository(db)
        try:
            _run(db, jobs, job_id)
        except Exception:
            logger.exception("AI job %s crashed", job_id)
            db.rollback()
            jobs.release_active_key(job_id, PROCESSING_FAILED_MESSAGE)


def _run(db: Session, jobs: AIJobRepository, job_id: str) -> None:
    job = jobs.get(job_id)
    jobs.mark_running(job)

    try:
        result = _process(db, job.parameters)
    except NotEnoughDocumentsError as exc:
        error = str(exc)
    except EmbeddingModelUnavailableError:
        error = MODEL_UNAVAILABLE_MESSAGE
    except Exception:
        logger.exception("AI job %s failed", job_id)
        error = PROCESSING_FAILED_MESSAGE
    else:
        jobs.mark_succeeded(job, asdict(result))
        return

    db.rollback()
    jobs.mark_failed(job, error)


def _process(db: Session, parameters: dict):
    from app.services.topic_model import TopicModelService

    return TopicModelService(db).process(**parameters)
