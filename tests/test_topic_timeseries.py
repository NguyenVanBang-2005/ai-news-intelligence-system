"""GET /api/v1/topics/timeseries: daily counts (UTC days, zero-filled) of trending topics."""

from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.models.article import Article
from app.models.source import Source

URL = "/api/v1/topics/timeseries"


def add_articles(engine: Engine, topic: str, times: list[dict]) -> None:
    """Store one article per entry; an entry may set published_at and/or created_at."""
    with Session(engine) as db:
        source = db.query(Source).first()
        if source is None:
            source = Source(name="Daily", feed_url="https://daily.example/rss.xml")
            db.add(source)
            db.flush()
        start = db.query(Article).count()
        for offset, moments in enumerate(times, start=start):
            db.add(Article(
                source_id=source.id, title=f"{topic} {offset}", topic=topic,
                url=f"https://daily.example/{offset}", content="text", status="analyzed",
                **moments,
            ))
        db.commit()


def burst(engine: Engine, topic: str, count: int) -> list[datetime]:
    """`count` articles published a few seconds ago; returns their publish times."""
    now = datetime.now(UTC)
    times = [now - timedelta(seconds=n + 1) for n in range(count)]
    add_articles(engine, topic, [{"published_at": moment} for moment in times])
    return times


def get_series(client: TestClient, **params: object) -> list[dict]:
    response = client.get(URL, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def counts_by_date(series: dict) -> dict[str, int]:
    return {point["date"]: point["count"] for point in series["points"]}


def iso(moment: datetime) -> str:
    """The UTC calendar date of `moment`, as the API writes it."""
    return moment.astimezone(UTC).date().isoformat()


# --- shape and zero-fill -----------------------------------------------------------------


@pytest.mark.parametrize("days", [7, 30])
def test_points_cover_consecutive_utc_days_ending_today(
    client: TestClient, engine: Engine, days: int
) -> None:
    times = burst(engine, "chips", 3)

    [series] = get_series(client, days=days)

    dates = [date.fromisoformat(point["date"]) for point in series["points"]]
    today = datetime.now(UTC).date()
    assert len(dates) == days
    assert dates == [today - timedelta(days=days - 1 - n) for n in range(days)]
    assert sum(point["count"] for point in series["points"]) == 3
    assert counts_by_date(series)[iso(times[0])] == 3


def test_days_without_articles_are_zero(client: TestClient, engine: Engine) -> None:
    times = burst(engine, "chips", 2)

    [series] = get_series(client)

    busy_day = iso(times[0])
    assert all(count == 0 for day, count in counts_by_date(series).items() if day != busy_day)


def test_default_is_seven_days(client: TestClient, engine: Engine) -> None:
    burst(engine, "chips", 2)

    [series] = get_series(client)

    assert len(series["points"]) == 7


def test_fields_match_trending(client: TestClient, engine: Engine) -> None:
    burst(engine, "chips", 4)

    [series] = get_series(client)
    [trend] = client.get("/api/v1/topics/trending").json()

    assert set(series) == {"topic", "trend_score", "article_count", "points"}
    assert (series["topic"], series["trend_score"], series["article_count"]) == (
        trend["topic"], trend["trend_score"], trend["article_count"]
    )


# --- which day an article falls on --------------------------------------------------------


def test_articles_at_a_day_boundary_fall_on_their_utc_day(
    client: TestClient, engine: Engine
) -> None:
    today_start = datetime.combine(datetime.now(UTC).date(), datetime.min.time(), tzinfo=UTC)
    just_before = today_start - timedelta(microseconds=1)
    # 01:00 at UTC+7 today is 18:00 UTC yesterday.
    local_morning = today_start.replace(tzinfo=timezone(timedelta(hours=7))) + timedelta(hours=1)
    add_articles(engine, "chips", [
        {"published_at": today_start},
        {"published_at": just_before},
        {"published_at": local_morning},
    ])

    [series] = get_series(client, window_hours=48, min_articles=1)

    counts = counts_by_date(series)
    assert counts[today_start.date().isoformat()] == 1
    assert counts[just_before.date().isoformat()] == 2


def test_articles_without_a_publish_date_use_when_they_were_collected(
    client: TestClient, engine: Engine
) -> None:
    times = burst(engine, "chips", 2)
    three_days_ago = datetime.now(UTC) - timedelta(days=3)
    add_articles(engine, "chips", [
        {"published_at": None, "created_at": three_days_ago},
        # A publish date wins over the collection time.
        {"published_at": three_days_ago, "created_at": times[0]},
    ])

    [series] = get_series(client, baseline_days=7)

    counts = counts_by_date(series)
    assert counts[iso(three_days_ago)] == 2
    assert counts[iso(times[0])] == 2


def test_articles_older_than_the_range_and_other_topics_are_not_counted(
    client: TestClient, engine: Engine
) -> None:
    burst(engine, "chips", 2)
    add_articles(engine, "chips", [{"published_at": datetime.now(UTC) - timedelta(days=10)}])
    add_articles(engine, "quiet topic", [{"published_at": datetime.now(UTC)}])

    result = get_series(client, days=7)

    assert [series["topic"] for series in result] == ["chips"]
    assert sum(point["count"] for point in result[0]["points"]) == 2


# --- which topics ------------------------------------------------------------------------


def test_catch_all_labels_are_left_out(client: TestClient, engine: Engine) -> None:
    burst(engine, "Other", 5)
    burst(engine, "Other / Outlier", 5)
    burst(engine, "chips", 2)

    assert [series["topic"] for series in get_series(client, limit=10)] == ["chips"]


def test_no_trending_topic_gives_an_empty_list(client: TestClient, engine: Engine) -> None:
    assert get_series(client) == []
    burst(engine, "single story", 1)  # below the default min_articles of 2

    assert get_series(client) == []


def test_strongest_trend_comes_first_and_limit_applies(
    client: TestClient, engine: Engine
) -> None:
    for topic, count in [("small", 2), ("large", 6), ("medium", 4), ("tiny", 3)]:
        burst(engine, topic, count)

    result = get_series(client, limit=2)

    assert [series["topic"] for series in result] == ["large", "medium"]
    scores = [series["trend_score"] for series in get_series(client, limit=10)]
    assert scores == sorted(scores, reverse=True) and len(scores) == 4


@pytest.mark.parametrize(
    "params",
    [
        {"days": 0}, {"days": 31}, {"limit": 0}, {"limit": 11},
        {"window_hours": 0}, {"window_hours": 169}, {"baseline_days": 0},
        {"baseline_days": 31}, {"min_articles": 0}, {"min_articles": 51},
    ],
)
def test_out_of_range_parameters_are_rejected(client: TestClient, params: dict) -> None:
    assert client.get(URL, params=params).status_code == 422


# --- query count -------------------------------------------------------------------------


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


def test_one_query_for_trending_and_one_for_points_whatever_the_topic_count(
    client: TestClient, engine: Engine
) -> None:
    with count_queries(engine) as nothing_trending:
        get_series(client)
    burst(engine, "first", 2)
    with count_queries(engine) as one_topic:
        assert len(get_series(client, limit=10)) == 1
    for name in ("second", "third", "fourth", "fifth"):
        burst(engine, name, 3)
    with count_queries(engine) as five_topics:
        assert len(get_series(client, limit=10)) == 5

    assert len(nothing_trending) == 1  # no points query when nothing trends
    assert len(one_topic) == len(five_topics) == 2
