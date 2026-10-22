"""AI jobs, cached article embeddings and topic details."""

import sqlalchemy as sa

from alembic import op

revision = "0003_ai_jobs_and_embeddings"
down_revision = "0002_topics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("articles", sa.Column("embedding", sa.LargeBinary(), nullable=True))
    op.add_column("articles", sa.Column("embedding_key", sa.String(64), nullable=True))
    op.add_column(
        "topics",
        sa.Column("keywords", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "topics",
        sa.Column("representative_article_ids", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.create_table(
        "ai_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_ai_jobs_status", "ai_jobs", ["status"])


def downgrade() -> None:
    op.drop_table("ai_jobs")
    op.drop_column("topics", "representative_article_ids")
    op.drop_column("topics", "keywords")
    op.drop_column("articles", "embedding_key")
    op.drop_column("articles", "embedding")
