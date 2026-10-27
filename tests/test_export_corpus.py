"""Corpus export script: sampling, labeler assignment, CSV layout, and read-only behaviour."""

import csv
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.models.article import Article
from app.models.source import Source
from app.services.topic_model import OUTLIER_LABEL
from scripts.export_corpus import COLUMNS, assign_labelers, build_rows, make_excerpt, write_csv


def add_articles(db: Session, counts: dict[str, int], status: str = "ai_analyzed") -> None:
    for name, count in counts.items():
        source = Source(name=name, feed_url=f"https://{name}.test/feed")
        db.add(source)
        db.flush()
        for index in range(count):
            db.add(
                Article(
                    source_id=source.id,
                    title=f"{name} title {index}",
                    url=f"https://{name}.test/{index}",
                    content="robot research\nsecond line",
                    summary="short summary",
                    topic="robot · ai",
                    confidence=0.9,
                    status=status,
                    published_at=datetime(2026, 1, 2, 3, 4, tzinfo=UTC),
                )
            )
    db.commit()


def export(engine: Engine, size: int = 30, seed: int = 42, shared: int = 10):
    with Session(engine) as db:
        return build_rows(db, size, seed, labelers=4, shared=shared)


def test_same_seed_gives_same_ids(engine: Engine) -> None:
    with Session(engine) as db:
        add_articles(db, {"a": 20, "b": 20, "c": 20})
    first, _ = export(engine)
    second, _ = export(engine)
    assert [r["article_id"] for r in first] == [r["article_id"] for r in second]


def test_small_source_gives_all_and_rest_share_quota(engine: Engine) -> None:
    with Session(engine) as db:
        add_articles(db, {"small": 5, "b": 30, "c": 30, "d": 30})
    rows, _ = export(engine, size=30)
    counts = Counter(r["source"] for r in rows)
    assert counts["small"] == 5
    assert len(rows) == 30
    assert sorted(counts[s] for s in "bcd") == [8, 8, 9]


def test_fewer_articles_than_size_exports_all(engine: Engine) -> None:
    with Session(engine) as db:
        add_articles(db, {"a": 4, "b": 3})
    rows, _ = export(engine, size=30)
    assert len(rows) == 7


def test_skips_articles_that_are_not_analyzed(engine: Engine) -> None:
    with Session(engine) as db:
        add_articles(db, {"a": 5})
        add_articles(db, {"b": 2}, status="missing_content")
    rows, excluded = export(engine)
    assert {r["source"] for r in rows} == {"a"}
    assert excluded == {"missing_content": 2}


def test_assigned_to_counts() -> None:
    assigned = assign_labelers(count=50, labelers=4, shared=10)
    counts = Counter(assigned)
    assert counts["all"] == 10
    assert sorted(counts[f"L{n}"] for n in range(1, 5)) == [10, 10, 10, 10]
    assert assigned[:10] == ["all"] * 10


def test_csv_columns_and_empty_human_cells(engine: Engine, tmp_path: Path) -> None:
    with Session(engine) as db:
        add_articles(db, {"a": 12})
    rows, _ = export(engine)
    out = tmp_path / "nested" / "corpus.csv"
    write_csv(rows, out)
    with out.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        read_back = list(reader)
    assert reader.fieldnames == COLUMNS
    for name in ("human_ai_relevant", "human_topic", "human_topic_fit", "human_summary_ok"):
        assert all(row[name] == "" for row in read_back)
    assert len(read_back) == 12


def test_excerpt_has_no_newlines_and_is_capped() -> None:
    excerpt = make_excerpt("line one\r\nline two\n" + "x" * 2000)
    assert "\n" not in excerpt and "\r" not in excerpt
    assert len(excerpt) == 800


def test_null_summary_and_outlier_flag(engine: Engine) -> None:
    with Session(engine) as db:
        add_articles(db, {"a": 2})
        first, second = db.scalars(select(Article).order_by(Article.id)).all()
        first.summary = None
        second.topic = OUTLIER_LABEL
        db.commit()
        first_id, second_id = first.id, second.id
    rows, _ = export(engine)
    by_id = {int(r["article_id"]): r for r in rows}
    assert by_id[first_id]["system_summary"] == ""
    assert by_id[first_id]["system_is_outlier"] == 0
    assert by_id[second_id]["system_is_outlier"] == 1


def test_baseline_topic_is_filled(engine: Engine) -> None:
    with Session(engine) as db:
        add_articles(db, {"a": 1})
    rows, _ = export(engine)
    assert rows[0]["baseline_topic"] == "Robotics"


def test_export_does_not_write_to_database(engine: Engine) -> None:
    with Session(engine) as db:
        add_articles(db, {"a": 15, "b": 15})

    def table_counts() -> tuple[int, int]:
        with Session(engine) as db:
            return tuple(db.scalar(select(func.count()).select_from(m)) for m in (Article, Source))

    before = table_counts()
    export(engine)
    assert table_counts() == before


def test_rows_are_not_grouped_by_source(engine: Engine) -> None:
    with Session(engine) as db:
        add_articles(db, {"a": 20, "b": 20})
    rows, _ = export(engine)
    sources = [r["source"] for r in rows]
    assert sources != sorted(sources)
