"""Corpus export script: stratified sampling, CSV layout and read-only behaviour."""

import csv
import hashlib
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.db.base  # noqa: F401  (registers all models on Base.metadata)
from app.db.session import Base
from app.models.article import Article
from app.models.source import Source
from scripts.export_corpus import (
    COLUMNS,
    OUTLIER_LABEL,
    load_articles,
    proportional_quotas,
    stratified_sample,
    to_csv_row,
    write_csv,
)


def fake_rows(plan: dict[tuple[str, str], int]) -> list[dict]:
    """In-memory articles: plan maps (source, topic) to how many articles to make."""
    rows = []
    for (source, topic), count in plan.items():
        for _ in range(count):
            rows.append({"id": len(rows) + 1, "title": "t", "url": f"https://x.test/{len(rows)}",
                         "source_name": source, "published_at": None,
                         "model_topic": topic, "model_confidence": 0.5})  # fmt: skip
    return rows


def make_db(path: Path, plan: dict[tuple[str, str], int], status: str = "ai_analyzed") -> Path:
    """A real SQLite file with the app schema, filled from a (source, topic) plan."""
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        sources: dict[str, Source] = {}
        for (name, topic), count in plan.items():
            if name not in sources:
                sources[name] = Source(name=name, feed_url=f"https://{name}.test/")
                db.add(sources[name])
            for n in range(count):
                db.add(Article(source=sources[name], title=f"{name} {n}",
                               url=f"https://{name}.test/{topic}/{n}", content="body",
                               topic=topic, confidence=0.75, status=status,
                               published_at=datetime(2026, 1, 2, 3, 4, tzinfo=UTC)))  # fmt: skip
        db.commit()
    engine.dispose()
    return path


def test_quotas_follow_source_sizes() -> None:
    quotas = proportional_quotas(Counter({"big": 100, "mid": 50, "small": 50}), 50)
    assert quotas == {"big": 25, "mid": 13, "small": 12}  # tie on .5 goes to the first name


def test_sample_is_proportional_by_source() -> None:
    rows = fake_rows({("a", "T1"): 100, ("b", "T1"): 60, ("c", "T1"): 40})
    counts = Counter(r["source_name"] for r in stratified_sample(rows, 50, seed=1))
    assert counts == {"a": 25, "b": 15, "c": 10}


def test_every_topic_and_five_outliers_are_covered() -> None:
    rows = fake_rows({("a", "Main"): 180, ("a", "Rare"): 2, ("b", OUTLIER_LABEL): 8})
    sample = stratified_sample(rows, 50, seed=3)
    topics = Counter(r["model_topic"] for r in sample)
    assert len(sample) == 50
    assert topics["Rare"] >= 1
    assert topics[OUTLIER_LABEL] >= 5


def test_small_topic_gets_at_most_its_share() -> None:
    rows = fake_rows({("a", "Main"): 190, ("b", "Small"): 10})
    topics = Counter(r["model_topic"] for r in stratified_sample(rows, 50, seed=5))
    assert topics["Small"] <= 3  # ceil(50 * 10 / 200)


def test_same_seed_same_sample_and_different_seed_differs() -> None:
    rows = fake_rows({("a", "T1"): 80, ("b", "T2"): 80})
    ids = [[r["id"] for r in stratified_sample(rows, 30, seed=s)] for s in (7, 7, 8)]
    assert ids[0] == ids[1]
    assert ids[0] != ids[2]


def test_fewer_articles_than_size_exports_all() -> None:
    rows = fake_rows({("a", "T1"): 4, ("b", OUTLIER_LABEL): 3})
    assert len(stratified_sample(rows, 50, seed=1)) == 7


def test_load_skips_unanalyzed_and_keeps_db_unchanged(tmp_path: Path) -> None:
    db_path = make_db(tmp_path / "eval.db", {("a", "T1"): 3})
    make_db(db_path, {("b", "T1"): 2}, status="missing_content")
    before = hashlib.sha256(db_path.read_bytes()).hexdigest()
    rows = load_articles(db_path)
    assert {r["source_name"] for r in rows} == {"a"}
    assert hashlib.sha256(db_path.read_bytes()).hexdigest() == before


def test_missing_db_raises_instead_of_creating_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_articles(tmp_path / "missing.db")
    assert not (tmp_path / "missing.db").exists()


def test_csv_has_exact_columns_and_empty_human_cells(tmp_path: Path) -> None:
    db_path = make_db(tmp_path / "eval.db", {("a", "T1"): 6, ("b", OUTLIER_LABEL): 2})
    out = tmp_path / "nested" / "corpus.csv"
    write_csv([to_csv_row(r) for r in load_articles(db_path)], out)
    with out.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    assert reader.fieldnames == COLUMNS
    human = ("extractive_summary_ok", "human_topic", "topic_correct",
             "summary_score_1_to_5", "notes")  # fmt: skip
    assert all(row[name] == "" for row in rows for name in human)
    assert rows[0]["published_at"] == "2026-01-02 03:04 UTC"
    assert rows[0]["model_confidence"] == "0.75"
    assert not {"content", "summary", "excerpt"} & set(reader.fieldnames)
