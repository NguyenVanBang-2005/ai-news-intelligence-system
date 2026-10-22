"""Source types: RSS feeds and news API searches."""

import sqlalchemy as sa

from alembic import op

revision = "0005_source_types"
down_revision = "0004_article_ai_summary"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Batch mode lets SQLite change a column's nullability (it rebuilds the table).
    with op.batch_alter_table("sources") as batch:
        batch.add_column(
            sa.Column("type", sa.String(20), nullable=False, server_default="rss")
        )
        batch.add_column(sa.Column("query", sa.String(200), nullable=True))
        batch.alter_column("feed_url", existing_type=sa.String(1000), nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM sources WHERE feed_url IS NULL")
    with op.batch_alter_table("sources") as batch:
        batch.alter_column("feed_url", existing_type=sa.String(1000), nullable=False)
        batch.drop_column("query")
        batch.drop_column("type")
