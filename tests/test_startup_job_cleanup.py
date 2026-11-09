"""At startup the lifespan fails AI jobs that a previous run left pending or running."""

import logging
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.main
from app.models.ai_job import AIJob
from app.repositories.ai_job import ACTIVE_KEY, AIJobRepository
from app.services import ai_jobs
from tests.pg_support import client_for

TIMEOUT = 3600
FINISHED_AT = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture(autouse=True)
def real_startup_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    """conftest turns the cleanup off; here it runs, on the test database only."""
    monkeypatch.setattr(app.main, "fail_interrupted_jobs", ai_jobs.fail_interrupted_jobs)


def add_job(engine: Engine, job_id: str, status: str, active_key: str | None = None) -> None:
    """Store a job as a previous run of the app would have left it."""
    with Session(engine) as db:
        finished_at = FINISHED_AT if status == "succeeded" else None
        db.add(AIJob(id=job_id, status=status, parameters={}, active_key=active_key,
                     finished_at=finished_at, created_at=datetime.now(UTC)))
        db.commit()


def get_job(engine: Engine, job_id: str) -> AIJob:
    with Session(engine) as db:
        return db.get(AIJob, job_id)


def start_app(engine: Engine) -> None:
    """Run the app's startup and shutdown once against `engine`."""
    for _client in client_for(engine):
        pass


def test_running_and_pending_jobs_are_failed_at_startup(engine: Engine) -> None:
    # The unique active_key allows one active job; the pending one stands for older data.
    add_job(engine, "running", "running", active_key=ACTIVE_KEY)
    add_job(engine, "pending", "pending")
    before = datetime.now(UTC) - timedelta(seconds=5)

    start_app(engine)

    for job_id in ("running", "pending"):
        job = get_job(engine, job_id)
        assert job.status == "failed"
        assert job.error == "Interrupted by application restart"
        assert job.active_key is None
        assert job.finished_at >= before


def test_a_new_job_can_start_right_after_startup(engine: Engine) -> None:
    add_job(engine, "running", "running", active_key=ACTIVE_KEY)

    start_app(engine)

    with Session(engine) as db:
        jobs = AIJobRepository(db)
        assert jobs.find_active(max_age_seconds=TIMEOUT) is None
        assert jobs.create({}, max_age_seconds=TIMEOUT).status == "pending"


def test_finished_jobs_are_left_alone(engine: Engine) -> None:
    add_job(engine, "done", "succeeded")

    start_app(engine)

    job = get_job(engine, "done")
    assert (job.status, job.error, job.finished_at) == ("succeeded", None, FINISHED_AT)


def test_cleanup_is_safe_to_run_twice(engine: Engine) -> None:
    add_job(engine, "running", "running", active_key=ACTIVE_KEY)

    start_app(engine)
    first = get_job(engine, "running")
    start_app(engine)
    second = get_job(engine, "running")

    assert (second.status, second.error) == ("failed", "Interrupted by application restart")
    assert second.finished_at == first.finished_at


def test_startup_survives_a_database_without_tables(caplog: pytest.LogCaptureFixture) -> None:
    empty = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    with caplog.at_level(logging.WARNING, logger="app.services.ai_jobs"):
        for client in client_for(empty):
            assert client.get("/api/v1/health").status_code == 200

    assert "Could not fail interrupted AI jobs" in caplog.text
    empty.dispose()
