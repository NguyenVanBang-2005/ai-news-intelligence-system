"""Only one AI job may be pending/running: enforced by the unique ai_jobs.active_key."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier, Thread

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.models.ai_job import AIJob
from app.repositories.ai_job import AIJobAlreadyActiveError, AIJobRepository
from app.services.ai_jobs import run_ai_job
from tests.pg_support import requires_postgres
from tests.test_database_migrations import migrate

TIMEOUT = 3600


def create_job(engine: Engine) -> str:
    with Session(engine) as db:
        return AIJobRepository(db).create({}, max_age_seconds=TIMEOUT).id


def get_job(engine: Engine, job_id: str) -> AIJob:
    with Session(engine) as db:
        return db.get(AIJob, job_id)


def test_second_job_is_refused_until_the_first_one_finishes(engine: Engine) -> None:
    first_id = create_job(engine)

    with pytest.raises(AIJobAlreadyActiveError):
        create_job(engine)

    with Session(engine) as db:
        jobs = AIJobRepository(db)
        jobs.mark_succeeded(jobs.get(first_id), {})
    assert get_job(engine, first_id).active_key is None
    assert create_job(engine) != first_id


def test_failed_job_releases_the_lock(engine: Engine) -> None:
    with Session(engine) as db:
        jobs = AIJobRepository(db)
        jobs.mark_failed(jobs.get(create_job(engine)), "boom")

    create_job(engine)


def test_timed_out_job_is_failed_and_replaced(engine: Engine) -> None:
    with Session(engine) as db:
        db.add(AIJob(id="old", status="running", parameters={}, active_key="ai_process",
                     created_at=datetime.now(UTC) - timedelta(days=1)))
        db.commit()

    new_id = create_job(engine)

    old = get_job(engine, "old")
    assert (old.status, old.active_key, old.error) == ("failed", None, "AI job timed out.")
    assert get_job(engine, new_id).active_key == "ai_process"


def test_unexpected_crash_still_releases_the_lock(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    job_id = create_job(engine)

    def crash(*args: object) -> None:
        raise RuntimeError("unexpected")

    monkeypatch.setattr("app.services.ai_jobs._process", crash)
    monkeypatch.setattr(AIJobRepository, "mark_failed", crash)  # even recording the error fails
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    run_ai_job(job_id, factory)

    job = get_job(engine, job_id)
    assert (job.status, job.active_key) == ("failed", None)


@requires_postgres
def test_two_simultaneous_creates_make_exactly_one_job(engine: Engine) -> None:
    """Real race: two threads, two independent sessions, released at the same moment."""
    if engine.dialect.name != "postgresql":
        pytest.skip("real race needs PostgreSQL (SQLite runs the sequential IntegrityError test)")
    barrier, outcomes = Barrier(2), []

    def attempt() -> None:
        with Session(engine) as db:
            barrier.wait()
            try:
                AIJobRepository(db).create({}, max_age_seconds=TIMEOUT)
                outcomes.append("created")
            except AIJobAlreadyActiveError:
                outcomes.append("refused")

    threads = [Thread(target=attempt) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]

    assert sorted(outcomes) == ["created", "refused"]


def _insert_job(connection, job_id: str, status: str, minute: int) -> None:
    connection.execute(
        text("INSERT INTO ai_jobs (id, status, parameters, created_at) "
             "VALUES (:id, :status, '{}', :created)"),
        {"id": job_id, "status": status,
         "created": datetime(2026, 9, 1, 0, minute, tzinfo=UTC).isoformat()},
    )


def check_migration_roundtrip(url: str) -> None:
    migrate(url, "upgrade", "0005_source_types")
    engine = create_engine(url)
    try:
        with engine.begin() as conn:
            _insert_job(conn, "old", "running", 1)
            _insert_job(conn, "new", "pending", 2)
            _insert_job(conn, "done", "succeeded", 3)

        migrate(url, "upgrade", "head")
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT id, status, active_key, error FROM ai_jobs ORDER BY id")
            ).all()
        assert rows == [
            ("done", "succeeded", None, None),
            ("new", "pending", "ai_process", None),
            ("old", "failed", None, "superseded during migration"),
        ]

        migrate(url, "downgrade", "0005_source_types")
        migrate(url, "upgrade", "head")
        migrate(url, "check")
    finally:
        engine.dispose()


def test_migration_backfill_and_roundtrip_on_sqlite(tmp_path: Path) -> None:
    check_migration_roundtrip(f"sqlite:///{(tmp_path / 'lock.db').as_posix()}")


@requires_postgres
def test_migration_backfill_and_roundtrip_on_postgres(
    new_postgres_db: Callable[[], str],
) -> None:
    check_migration_roundtrip(new_postgres_db())
