"""The database in use is shown at startup and by scripts/create_admin.py, never its password."""

import logging

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import database_label, session_factory_database_label
from tests.pg_support import client_for

SECRET_URL = "postgresql+psycopg://u:SECRET@h:5432/db"


def test_label_masks_the_password() -> None:
    label = database_label(SECRET_URL)
    assert "SECRET" not in label
    assert label == "postgresql+psycopg://u:***@h:5432/db"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("sqlite:///local-data/ainis_eval_v2.db", "sqlite:///local-data/ainis_eval_v2.db"),
        ("sqlite://", "sqlite://"),
        ("postgresql+psycopg://news@127.0.0.1:5432/news", "postgresql+psycopg://news@127.0.0.1:5432/news"),
    ],
)
def test_label_keeps_urls_without_a_password(url: str, expected: str) -> None:
    assert database_label(url) == expected


def test_label_of_a_session_factory_uses_its_engine() -> None:
    engine = create_engine(SECRET_URL)  # never connects
    try:
        label = session_factory_database_label(sessionmaker(bind=engine))
    finally:
        engine.dispose()
    assert label == "postgresql+psycopg://u:***@h:5432/db"


def test_startup_logs_the_database_without_its_password(caplog: pytest.LogCaptureFixture) -> None:
    engine = create_engine(SECRET_URL)  # the lifespan only reads its URL
    caplog.set_level(logging.INFO, logger="uvicorn.error")
    try:
        for _ in client_for(engine):
            pass
    finally:
        engine.dispose()
    lines = [record.getMessage() for record in caplog.records if record.name == "uvicorn.error"]
    assert "Database: postgresql+psycopg://u:***@h:5432/db" in lines
    assert "SECRET" not in caplog.text
