from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


if settings.database_url.startswith("sqlite:///./"):
    Path("data").mkdir(parents=True, exist_ok=True)

def database_connect_args(url: str) -> dict:
    if url.startswith("sqlite"):
        return {"check_same_thread": False}
    if url.startswith("postgresql"):
        return {"options": "-c timezone=UTC"}
    return {}


engine = create_engine(
    settings.database_url,
    connect_args=database_connect_args(settings.database_url),
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def database_label(url: str | URL) -> str:
    """The database URL for logs and script output, with the password masked (***)."""
    return make_url(url).render_as_string(hide_password=True)


def session_factory_database_label(factory: sessionmaker[Session]) -> str:
    """database_label of the engine a session factory is bound to (settings if unbound)."""
    bind = factory.kw.get("bind")
    return database_label(bind.url if bind is not None else settings.database_url)


def get_session_factory() -> sessionmaker[Session]:
    """For work that outlives the request (background jobs) and needs its own sessions."""
    return SessionLocal


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

