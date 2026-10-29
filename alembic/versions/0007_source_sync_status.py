"""Sync status per source: when it was last ingested, the outcome and a short error."""

import sqlalchemy as sa

from alembic import op

revision = "0007_source_sync_status"
down_revision = "0006_ai_job_active_key"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable: sources that were never synced keep NULL in all three columns.
    with op.batch_alter_table("sources") as batch:
        batch.add_column(sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("last_status", sa.String(10), nullable=True))
        batch.add_column(sa.Column("last_error", sa.String(300), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("sources") as batch:
        batch.drop_column("last_error")
        batch.drop_column("last_status")
        batch.drop_column("last_synced_at")
