from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
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


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

