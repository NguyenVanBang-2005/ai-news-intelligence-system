"""corpus_stats: the source x topic table, on a tiny SQLite file (no real data)."""

import sqlite3
from pathlib import Path

from scripts.corpus_stats import connect_read_only, source_by_topic


def make_db(path: Path) -> Path:
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE sources (id INTEGER PRIMARY KEY, name TEXT)")
    db.execute("CREATE TABLE articles (id INTEGER PRIMARY KEY, source_id INT, topic TEXT)")
    db.executemany("INSERT INTO sources VALUES (?, ?)", [(1, "A"), (2, "B")])
    rows = [(1, "big")] * 3 + [(2, "big"), (2, "small"), (2, None)]
    db.executemany("INSERT INTO articles (source_id, topic) VALUES (?, ?)", rows)
    db.commit()
    db.close()
    return path


def test_source_by_topic_counts_and_legend(tmp_path: Path) -> None:
    db = connect_read_only(make_db(tmp_path / "s.db"))
    text = source_by_topic(db)
    db.close()
    lines = [line.split() for line in text.splitlines()]
    assert ["source", "T1", "T2", "T3", "total"] in lines
    assert ["A", "3", "0", "0", "3"] in lines
    assert ["B", "1", "1", "1", "3"] in lines
    assert ["total", "4", "1", "1", "6"] in lines
    assert "T1 = big" in text
    assert "= (none)" in text and "= small" in text  # T2/T3 tie, order not fixed
