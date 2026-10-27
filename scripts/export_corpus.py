"""Export a sample of analyzed articles to CSV so the team can label them by hand.

Read-only: it only SELECTs from the database and never calls the network.
Run inside the api container:  python /tmp/export_corpus.py --out /tmp/corpus_to_label.csv
"""

import argparse
import csv
import random
import re
from collections import Counter
from datetime import UTC
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.article import Article
from app.models.source import Source
from app.services.analyzer import HeuristicAnalyzer
from app.services.topic_model import OUTLIER_LABEL

EXPORTED_STATUS = "ai_analyzed"
EXCERPT_CHARS = 800
MIN_SIZE, MAX_SIZE = 30, 50

COLUMNS = [
    "article_id", "assigned_to", "source", "published_at_utc", "title", "url", "excerpt",
    "human_ai_relevant", "human_topic",
    "system_topic", "system_confidence", "system_is_outlier", "system_summary",
    "human_topic_fit", "human_summary_ok", "labeler", "notes",
    "baseline_topic",
]  # fmt: skip


def fetch_articles(db: Session) -> tuple[list[tuple[Article, str]], Counter]:
    """Return (article, source name) pairs to export, plus excluded counts by status."""
    rows = db.execute(
        select(Article, Source.name)
        .join(Source, Source.id == Article.source_id)
        .order_by(Article.id)
    ).all()
    kept = [(article, name) for article, name in rows if article.status == EXPORTED_STATUS]
    excluded = Counter(article.status for article, _ in rows if article.status != EXPORTED_STATUS)
    return kept, excluded


def sample_by_source(
    rows: list[tuple[Article, str]], size: int, rng: random.Random
) -> list[tuple[Article, str]]:
    """Water-filling: small sources give all they have, the rest share the remaining quota."""
    by_source: dict[str, list] = {}
    for row in rows:
        by_source.setdefault(row[1], []).append(row)
    if len(rows) <= size:
        return list(rows)
    chosen: list = []
    remaining = size
    while True:
        quota = remaining // len(by_source)
        small = [name for name, items in by_source.items() if len(items) <= quota]
        if not small:
            break
        for name in small:
            chosen += by_source.pop(name)
        remaining = size - len(chosen)
    leftovers: list = []
    for name in sorted(by_source):
        picked = rng.sample(by_source[name], quota)
        chosen += picked
        leftovers += [row for row in by_source[name] if row not in picked]
    extra = size - len(chosen)
    return chosen + rng.sample(leftovers, extra)


def assign_labelers(count: int, labelers: int, shared: int) -> list[str]:
    """First `shared` rows go to everyone ("all"); the rest rotate L1..L{labelers}."""
    shared = min(shared, count)
    rest = [f"L{index % labelers + 1}" for index in range(count - shared)]
    return ["all"] * shared + rest


def make_excerpt(content: str) -> str:
    """First ~800 characters of the article with line breaks turned into spaces."""
    return re.sub(r"\s+", " ", content or "").strip()[:EXCERPT_CHARS]


def to_row(article: Article, source_name: str, assigned_to: str) -> dict[str, str]:
    """Build one CSV row; human columns stay empty for the team to fill in."""
    published = article.published_at
    row = dict.fromkeys(COLUMNS, "")
    row.update(
        article_id=article.id,
        assigned_to=assigned_to,
        source=source_name,
        published_at_utc=published.astimezone(UTC).strftime("%Y-%m-%d %H:%M") if published else "",
        title=re.sub(r"\s+", " ", article.title or "").strip(),
        url=article.url,
        excerpt=make_excerpt(article.content),
        system_topic=article.topic or "",
        system_confidence="" if article.confidence is None else article.confidence,
        system_is_outlier=int(article.topic == OUTLIER_LABEL),
        system_summary=re.sub(r"\s+", " ", article.summary or "").strip(),
        baseline_topic=HeuristicAnalyzer()
        .analyze(article.title or "", article.content or "")
        .topic,
    )
    return row


def build_rows(db: Session, size: int, seed: int, labelers: int, shared: int):
    """Fetch, sample, shuffle and label; returns (rows, excluded counts by status)."""
    rng = random.Random(seed)
    kept, excluded = fetch_articles(db)
    sampled = sample_by_source(kept, size, rng)
    rng.shuffle(sampled)
    assigned = assign_labelers(len(sampled), labelers, shared)
    return [to_row(a, s, who) for (a, s), who in zip(sampled, assigned, strict=True)], excluded


def write_csv(rows: list[dict[str, str]], out: Path) -> None:
    """Write UTF-8 with BOM so Excel opens Vietnamese/accents correctly."""
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def print_summary(rows: list[dict], excluded: Counter, out: Path) -> None:
    """Print counts only, never article text."""
    print(f"Exported: {len(rows)}")
    print("By source:", dict(Counter(r["source"] for r in rows)))
    topics = Counter(r["system_topic"] for r in rows)
    outliers = sum(r["system_is_outlier"] for r in rows)
    print(f"Outliers: {outliers}/{len(rows)} ({outliers / max(len(rows), 1):.0%})")
    print("By system_topic:", dict(topics))
    print("By assigned_to:", dict(Counter(r["assigned_to"] for r in rows)))
    print(f"Excluded (status != {EXPORTED_STATUS}): {sum(excluded.values())} {dict(excluded)}")
    print(f"File: {out}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=int, default=50)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--labelers", type=int, default=4)
    parser.add_argument("--shared", type=int, default=10)
    parser.add_argument("--out", type=Path, default=Path("data/corpus/corpus_to_label.csv"))
    args = parser.parse_args()
    if not MIN_SIZE <= args.size <= MAX_SIZE:
        parser.error(f"--size must be between {MIN_SIZE} and {MAX_SIZE}")
    return args


def main() -> None:
    from app.db.session import SessionLocal

    args = parse_args()
    with SessionLocal() as db:
        rows, excluded = build_rows(db, args.size, args.seed, args.labelers, args.shared)
    write_csv(rows, args.out)
    print_summary(rows, excluded, args.out)


if __name__ == "__main__":
    main()
