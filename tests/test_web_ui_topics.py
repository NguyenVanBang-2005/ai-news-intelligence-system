"""The Topics page (#/topics): module wiring, safe-markup rules, and the API answers it uses.

File reads and TestClient requests only; no browser and no Node.
"""

import re
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.main import STATIC_DIR
from app.models.article import Article
from app.models.source import Source
from app.models.topic import Topic

PAGES = STATIC_DIR / "js" / "pages"
TOPIC_MODULES = ["topics.js", "topic-cards.js", "topic-chart.js", "topic-articles.js"]
OUTLIER = "Other / Outlier"


def read_page(name: str) -> str:
    return (PAGES / name).read_text(encoding="utf-8")


def test_topics_route_shows_the_topics_page() -> None:
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")

    assert 'topics: { title: "Topics", render: renderTopicsPage }' in app_js
    assert "comingSoon" not in app_js


ALL_JS = sorted((STATIC_DIR / "js").rglob("*.js")) + [STATIC_DIR / "app.js"]


@pytest.mark.parametrize("path", ALL_JS, ids=lambda p: p.name)
def test_no_script_touches_element_style(path) -> None:
    # Bars are <progress> elements and the chart uses SVG attributes, so no file needs it.
    source = path.read_text(encoding="utf-8")

    assert ".style" not in source, path.name
    assert "style=" not in source, path.name


def test_topic_modules_load_nothing_from_other_origins() -> None:
    for name in TOPIC_MODULES:
        urls = re.findall(r"https?://[^\s\"'`]+", read_page(name))
        # The only absolute URL is the SVG namespace name, which is never fetched.
        assert set(urls) <= {"http://www.w3.org/2000/svg"}, name


def test_chart_is_built_with_svg_attributes() -> None:
    chart = read_page("topic-chart.js")

    assert "document.createElementNS(SVG_NS" in chart
    assert 'throw new TypeError("svgNode() does not set style")' in chart


def test_outlier_label_matches_the_backend() -> None:
    # Compared as text: importing app.services.topic_model would load the whole ML stack.
    backend = (STATIC_DIR.parent / "services" / "topic_model.py").read_text(encoding="utf-8")

    assert f'OUTLIER_LABEL = "{OUTLIER}"' in backend
    assert f'export const OUTLIER_LABEL = "{OUTLIER}";' in read_page("topics.js")


def test_fixed_texts_hold_no_token_or_command() -> None:
    page = read_page("topics.js") + read_page("topic-cards.js")

    assert '"No topics yet. An admin can run AI processing."' in page
    assert '"Articles that did not fit any topic"' in page
    assert "X-Admin-Token" not in page and "/ai/process" not in page


def add_articles(engine: Engine) -> None:
    """Two topic articles (older, newer), one outlier, and a stored topic row."""
    with Session(engine) as db:
        source = Source(name="S", feed_url="https://s.test/rss")
        db.add(source)
        db.flush()
        rows = [("a · b", 1), ("a · b", 3), (OUTLIER, 2)]
        for index, (topic, day) in enumerate(rows):
            db.add(Article(source_id=source.id, title=f"t{index}", url=f"https://s.test/{index}",
                           content="x", topic=topic, status="ai_analyzed",
                           published_at=datetime(2026, 10, day, tzinfo=UTC)))  # fmt: skip
        db.add(Topic(label="a · b", centroid=[1.0], article_count=2, keywords=[],
                     representative_article_ids=[]))  # fmt: skip
        db.commit()


def test_api_answers_the_page_relies_on(client: TestClient, engine: Engine) -> None:
    add_articles(engine)

    topics = client.get("/api/v1/ai/topics").json()
    assert [(t["label"], t["size"]) for t in topics] == [("a · b", 2)]  # no outlier entry
    assert client.get("/api/v1/articles", params={"limit": 1}).json()["total"] == 3
    outliers = client.get("/api/v1/articles", params={"topic": OUTLIER, "limit": 1}).json()
    assert outliers["total"] == 1
    page = client.get("/api/v1/articles", params={"topic": "a · b", "limit": 20}).json()
    assert [item["title"] for item in page["items"]] == ["t1", "t0"]  # newest first
