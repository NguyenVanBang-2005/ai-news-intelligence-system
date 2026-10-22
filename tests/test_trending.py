"""GET /api/v1/topics/trending: topics with more recent articles than usual."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.models.article import Article
from app.models.source import Source
from app.services.trending import trend_score

NOW = datetime.now(UTC)


def seed(engine: Engine, topics: dict[str, list[float]]) -> None:
    """`topics` maps a topic to the age in hours of each of its articles."""
    with Session(engine) as db:
        source = Source(name="Daily", feed_url="https://daily.example/rss.xml")
        db.add(source)
        db.flush()
        for topic, ages in topics.items():
            for n, age in enumerate(ages):
                db.add(Article(
                    source_id=source.id, title=f"{topic} {n}",
                    url=f"https://daily.example/{topic}/{n}", content="text",
                    topic=topic, status="analyzed",
                    published_at=NOW - timedelta(hours=age),
                ))
        db.commit()


def daily(count_per_day: int, days: int = 8) -> list[float]:
    """Ages of articles spread evenly: `count_per_day` per day over `days` days."""
    return [day * 24 + 1 + n for day in range(days) for n in range(count_per_day)]


def trending(client: TestClient, **params: object) -> list[dict]:
    response = client.get("/api/v1/topics/trending", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_a_burst_on_a_quiet_topic_beats_a_busy_but_steady_topic(
    client: TestClient, engine: Engine
) -> None:
    seed(engine, {
        "chip export ban": [1, 2, 3, 5, 8],   # 5 articles today, none before
        "ai regulation": daily(6),            # always about 6 a day
    })

    result = trending(client)

    assert [t["topic"] for t in result] == ["chip export ban"]
    burst = result[0]
    assert (burst["article_count"], burst["expected_count"]) == (5, 0.0)
    assert burst["trend_score"] == 5.0


def test_a_busy_topic_trends_when_it_is_busier_than_usual(
    client: TestClient, engine: Engine
) -> None:
    seed(engine, {"ai regulation": daily(2, days=8)[2:] + [1 + n * 0.5 for n in range(10)]})

    [topic] = trending(client)

    assert topic["topic"] == "ai regulation"
    assert topic["article_count"] == 10
    assert topic["expected_count"] == 2.0
    assert topic["trend_score"] == pytest.approx(trend_score(10, 2.0), abs=0.01)


def test_fading_topics_and_single_articles_do_not_trend(
    client: TestClient, engine: Engine
) -> None:
    seed(engine, {
        "last week's launch": [1] + [30 + n for n in range(20)],  # 1 today, 20 before
        "one-off story": [2],
    })

    assert trending(client) == []
    assert [t["topic"] for t in trending(client, min_articles=1)] == ["one-off story"]


def test_catch_all_labels_never_trend(client: TestClient, engine: Engine) -> None:
    seed(engine, {"Other": [1, 2, 3], "Other / Outlier": [1, 2, 3], "robotics": [1, 2]})

    assert [t["topic"] for t in trending(client)] == ["robotics"]


def test_articles_without_a_publish_date_count_from_when_they_were_collected(
    client: TestClient, engine: Engine
) -> None:
    with Session(engine) as db:
        source = Source(name="Daily", feed_url="https://daily.example/rss.xml")
        db.add(source)
        db.flush()
        for n in range(3):
            db.add(Article(source_id=source.id, title=f"undated {n}",
                           url=f"https://daily.example/undated/{n}", content="text",
                           topic="undated news", status="analyzed",
                           created_at=NOW - timedelta(hours=1)))
        db.commit()

    assert [t["topic"] for t in trending(client)] == ["undated news"]


def test_the_window_can_be_changed(client: TestClient, engine: Engine) -> None:
    seed(engine, {"weekly digest": [30, 40, 50]})  # yesterday-ish, outside a 24 h window

    assert trending(client) == []
    assert [t["topic"] for t in trending(client, window_hours=72)] == ["weekly digest"]


def test_strongest_burst_comes_first_and_limit_applies(
    client: TestClient, engine: Engine
) -> None:
    seed(engine, {"small": [1, 2], "big": [1, 2, 3, 4, 5, 6], "medium": [1, 2, 3, 4]})

    assert [t["topic"] for t in trending(client)] == ["big", "medium", "small"]
    assert [t["topic"] for t in trending(client, limit=1)] == ["big"]


@pytest.mark.parametrize("params", [{"window_hours": 0}, {"baseline_days": 31}, {"limit": 0}])
def test_out_of_range_parameters_are_rejected(client: TestClient, params: dict) -> None:
    assert client.get("/api/v1/topics/trending", params=params).status_code == 422


def test_trend_score_counts_standard_deviations_above_normal() -> None:
    assert trend_score(5, 0) == 5.0
    assert trend_score(4, 4) == 0.0
    assert trend_score(1, 3) < 0
