"""GET /api/v1/articles and /articles/{id} report source_name without a query per article."""

from collections.abc import Generator
from contextlib import contextmanager

from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.models.article import Article
from app.models.source import Source


def seed(engine: Engine, per_source: int) -> dict[str, list[int]]:
    """Two sources with `per_source` articles each; returns article ids by source name."""
    ids: dict[str, list[int]] = {}
    with Session(engine) as db:
        for name in ("Daily", "Weekly"):
            source = Source(name=name, feed_url=f"https://{name.lower()}.example/rss")
            db.add(source)
            db.flush()
            for index in range(per_source):
                article = Article(
                    source_id=source.id, title=f"{name} story {index}",
                    url=f"https://{name.lower()}.example/{index}", status="analyzed",
                )
                db.add(article)
                db.flush()
                ids.setdefault(name, []).append(article.id)
        db.commit()
    return ids


@contextmanager
def count_queries(engine: Engine) -> Generator[list[str], None, None]:
    """Collect every SQL statement the engine runs inside the block."""
    statements: list[str] = []

    def record(conn, cursor, statement, *args) -> None:
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", record)


def test_list_reports_each_article_source_name(client: TestClient, engine: Engine) -> None:
    ids = seed(engine, per_source=2)

    items = client.get("/api/v1/articles").json()["items"]

    names = {item["id"]: item["source_name"] for item in items}
    assert names == {article_id: name for name, group in ids.items() for article_id in group}


def test_detail_reports_source_name(client: TestClient, engine: Engine) -> None:
    ids = seed(engine, per_source=1)

    body = client.get(f"/api/v1/articles/{ids['Weekly'][0]}").json()

    assert body["source_name"] == "Weekly"


def test_list_query_count_does_not_grow_with_articles(
    client: TestClient, engine: Engine
) -> None:
    seed(engine, per_source=1)
    with count_queries(engine) as few:
        client.get("/api/v1/articles")

    seed_more(engine)
    with count_queries(engine) as many:
        items = client.get("/api/v1/articles", params={"limit": 100}).json()["items"]

    assert len(items) == 12
    assert len(many) == len(few)


def seed_more(engine: Engine) -> None:
    """Ten more articles spread over five new sources."""
    with Session(engine) as db:
        for source_index in range(5):
            source = Source(name=f"Extra {source_index}", feed_url=f"https://x{source_index}.example/rss")
            db.add(source)
            db.flush()
            for index in range(2):
                db.add(Article(
                    source_id=source.id, title=f"Extra {source_index}-{index}",
                    url=f"https://x{source_index}.example/{index}", status="analyzed",
                ))
        db.commit()
