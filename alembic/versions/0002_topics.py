"""Stored topic centroids, so topic labels stay stable across AI runs."""

import sqlalchemy as sa

from alembic import op

revision = "0002_topics"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "topics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("label", sa.String(80), nullable=False),
        sa.Column("centroid", sa.JSON(), nullable=False),
        sa.Column("article_count", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_topics_label", "topics", ["label"])


def downgrade() -> None:
    op.drop_table("topics")
