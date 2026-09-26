from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import Base, get_db
from app.main import app


def test_create_list_and_reject_duplicate_source() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)

    def override_db() -> Generator[Session, None, None]:
        with testing_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    payload = {
        "name": "Example AI News",
        "feed_url": "https://example.com/feed.xml",
        "language": "en",
    }
    try:
        with TestClient(app) as client:
            created = client.post("/api/v1/sources", json=payload)
            listed = client.get("/api/v1/sources")
            duplicate = client.post("/api/v1/sources", json=payload)
    finally:
        app.dependency_overrides.clear()

    assert created.status_code == 201
    assert created.json()["name"] == payload["name"]
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert duplicate.status_code == 409
