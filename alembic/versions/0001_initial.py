"""Initial sources and articles schema."""

import sqlalchemy as sa

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("feed_url", sa.String(1000), nullable=False),
        sa.Column("language", sa.String(10), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("feed_url"),
    )
    op.create_index("ix_sources_name", "sources", ["name"], unique=True)
    op.create_table(
        "articles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("url", sa.String(1500), nullable=False),
        sa.Column("author", sa.String(200), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("topic", sa.String(80), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    for column in ("source_id", "url", "topic", "status"):
        op.create_index(f"ix_articles_{column}", "articles", [column], unique=column == "url")


def downgrade() -> None:
    op.drop_table("articles")
    op.drop_table("sources")
