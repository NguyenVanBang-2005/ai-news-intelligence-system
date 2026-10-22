"""LLM-written article summaries for news search."""

import sqlalchemy as sa

from alembic import op

revision = "0004_article_ai_summary"
down_revision = "0003_ai_jobs_and_embeddings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("articles", sa.Column("ai_summary", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("articles", "ai_summary")
