"""Only one active AI job: active_key is unique and NULL once the job is finished."""

import sqlalchemy as sa

from alembic import context, op

revision = "0006_ai_job_active_key"
down_revision = "0005_source_types"
branch_labels = None
depends_on = None

ACTIVE_KEY = "ai_process"


def _keep_only_newest_active_job() -> None:
    """Older active jobs are failed, so the unique constraint can be created."""
    if context.is_offline_mode():  # --sql output cannot read rows; run online to backfill
        return
    connection = op.get_bind()
    active_ids = connection.execute(
        sa.text(
            "SELECT id FROM ai_jobs WHERE status IN ('pending', 'running') "
            "ORDER BY created_at DESC, id DESC"
        )
    ).scalars().all()
    superseded = sa.text(
        "UPDATE ai_jobs SET status = 'failed', error = 'superseded during migration', "
        "finished_at = CURRENT_TIMESTAMP WHERE id = :id"
    )
    for job_id in active_ids[1:]:
        connection.execute(superseded, {"id": job_id})
    if active_ids:
        connection.execute(
            sa.text("UPDATE ai_jobs SET active_key = :key WHERE id = :id"),
            {"key": ACTIVE_KEY, "id": active_ids[0]},
        )


def upgrade() -> None:
    with op.batch_alter_table("ai_jobs") as batch:
        batch.add_column(sa.Column("active_key", sa.String(30), nullable=True))
    _keep_only_newest_active_job()
    with op.batch_alter_table("ai_jobs") as batch:
        batch.create_unique_constraint("uq_ai_jobs_active_key", ["active_key"])


def downgrade() -> None:
    with op.batch_alter_table("ai_jobs") as batch:
        batch.drop_constraint("uq_ai_jobs_active_key", type_="unique")
        batch.drop_column("active_key")
