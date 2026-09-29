from sqlalchemy import create_engine, pool

import app.db.base  # noqa: F401
from alembic import context
from app.core.config import settings
from app.db.session import Base, database_connect_args
from app.db.types import UTCDateTime

target_metadata = Base.metadata


def render_item(kind, item, autogen_context):
    # Freeze the SQL type in revisions instead of importing a mutable application type.
    if kind == "type" and isinstance(item, UTCDateTime):
        return "sa.DateTime(timezone=True)"
    return False


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(
        settings.database_url,
        poolclass=pool.NullPool,
        connect_args=database_connect_args(settings.database_url),
    )
    with engine.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata, render_item=render_item
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
