"""Read-only corpus statistics for an AINIS SQLite database (counts only, no article text).

Example (from the repo root):
    python scripts/corpus_stats.py --db local-data/ainis_eval.db
"""

import argparse
import json
import sqlite3
import statistics
from pathlib import Path

OUTLIER_LABEL = "Other / Outlier"


def connect_read_only(db_path: Path) -> sqlite3.Connection:
    """mode=ro: SQLite refuses any write through this connection."""
    if not db_path.is_file():
        raise FileNotFoundError(f"Database not found: {db_path}")
    return sqlite3.connect(f"file:{db_path.resolve().as_posix()}?mode=ro", uri=True)


def table(title: str, header: list[str], rows: list[tuple]) -> str:
    """Render a plain-text table with left-aligned columns."""
    cells = [header] + [[str(v) for v in row] for row in rows]
    widths = [max(len(r[i]) for r in cells) for i in range(len(header))]
    lines = [title, "-" * len(title)]
    for index, row in enumerate(cells):
        lines.append("  ".join(v.ljust(w) for v, w in zip(row, widths, strict=True)).rstrip())
        if index == 0:
            lines.append("  ".join("-" * w for w in widths))
    return "\n".join(lines) + "\n"


def by_source(db: sqlite3.Connection) -> str:
    rows = db.execute(
        "SELECT s.name, s.last_status, COUNT(a.id) FROM sources s "
        "LEFT JOIN articles a ON a.source_id = s.id GROUP BY s.id ORDER BY s.id"
    ).fetchall()
    return table("Articles by source", ["source", "last_status", "articles"], rows)


def by_topic(db: sqlite3.Connection, total: int) -> str:
    rows = db.execute(
        "SELECT COALESCE(topic, '(none)'), COUNT(*) FROM articles "
        "GROUP BY topic ORDER BY COUNT(*) DESC"
    ).fetchall()
    shown = [(name, n, f"{n / total:.1%}") for name, n in rows]
    return table("Articles by topic (articles.topic)", ["topic", "articles", "share"], shown)


def topic_keywords(db: sqlite3.Connection) -> str:
    rows = db.execute(
        "SELECT id, label, article_count, keywords FROM topics ORDER BY id"
    ).fetchall()
    shown = []
    for topic_id, label, count, keywords in rows:
        words = [k["word"] for k in json.loads(keywords or "[]")[:5]]
        shown.append((topic_id, label, count, ", ".join(words)))
    header = ["id", "label", "article_count", "top 5 keywords"]
    return table("Stored topics (topics table)", header, shown)


def content_and_dates(db: sqlite3.Connection) -> str:
    lengths = [n for (n,) in db.execute("SELECT LENGTH(content) FROM articles")]
    dated = db.execute("SELECT COUNT(*) FROM articles WHERE published_at IS NOT NULL").fetchone()[0]
    missing = db.execute(
        "SELECT COUNT(*) FROM articles WHERE status = 'missing_content'"
    ).fetchone()[0]
    statuses = db.execute("SELECT status, COUNT(*) FROM articles GROUP BY status").fetchall()
    rows = [
        ("with published_at", dated),
        ("without published_at", len(lengths) - dated),
        ("median content length (chars)", int(statistics.median(lengths)) if lengths else 0),
        ("status missing_content", missing),
        ("status breakdown", ", ".join(f"{s}={n}" for s, n in statuses)),
    ]
    return table("Content and dates", ["metric", "value"], rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("local-data/ainis_eval.db"))
    args = parser.parse_args()
    db = connect_read_only(args.db)
    total = db.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    outliers = db.execute(
        "SELECT COUNT(*) FROM articles WHERE topic = ?", (OUTLIER_LABEL,)
    ).fetchone()[0]
    print(f"Total articles: {total}")
    print(f"Outliers ({OUTLIER_LABEL}): {outliers} ({outliers / max(total, 1):.1%})\n")
    for section in (by_source(db), by_topic(db, total), topic_keywords(db), content_and_dates(db)):
        print(section)


if __name__ == "__main__":
    main()
