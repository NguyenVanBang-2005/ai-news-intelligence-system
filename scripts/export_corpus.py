"""Export a stratified sample of AI-analyzed articles to CSV for manual labeling.

Read-only: opens the SQLite database with mode=ro and never calls the network.
The CSV has no article text and no summary; labelers read each article at its url.

Example (from the repo root):
    python scripts/export_corpus.py --db local-data/ainis_eval.db --size 50 --seed 42 \
        --out local-data/corpus_to_label.csv
"""

import argparse
import csv
import math
import random
import sqlite3
from collections import Counter
from pathlib import Path

# Same value as app.services.topic_model.OUTLIER_LABEL (not imported: it loads the ML stack).
OUTLIER_LABEL = "Other / Outlier"
EXPORTED_STATUS = "ai_analyzed"
MIN_OUTLIERS = 5

COLUMNS = [
    "id", "title", "url", "source_name", "published_at", "model_topic", "model_confidence",
    "extractive_summary_ok", "human_topic", "topic_correct", "summary_score_1_to_5", "notes",
]  # fmt: skip

QUERY = """
SELECT a.id, a.title, a.url, s.name AS source_name, a.published_at,
       a.topic AS model_topic, a.confidence AS model_confidence
FROM articles a JOIN sources s ON s.id = a.source_id
WHERE a.status = ? AND a.topic IS NOT NULL
ORDER BY a.id
"""


def load_articles(db_path: Path) -> list[dict]:
    """All analyzed articles as plain dicts; the database is opened read-only."""
    if not db_path.is_file():
        raise FileNotFoundError(f"Database not found: {db_path}")
    connection = sqlite3.connect(f"file:{db_path.resolve().as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in connection.execute(QUERY, (EXPORTED_STATUS,))]
    finally:
        connection.close()


def proportional_quotas(counts: Counter, size: int) -> dict[str, int]:
    """Split `size` across groups in proportion to their counts (largest remainder)."""
    total = sum(counts.values())
    exact = {name: size * n / total for name, n in counts.items()}
    quotas = {name: math.floor(value) for name, value in exact.items()}
    by_remainder = sorted(exact, key=lambda name: (quotas[name] - exact[name], name))
    for name in by_remainder[: size - sum(quotas.values())]:
        quotas[name] += 1
    return quotas


def source_targets(quotas: dict[str, int], used: Counter, size: int) -> dict[str, int]:
    """Per-source totals that respect forced picks and still add up to `size`.

    A source whose forced picks exceed its quota keeps them; the overflow is taken back
    one row at a time from the sources with the most room left.
    """
    targets = {source: max(quota, used[source]) for source, quota in quotas.items()}
    while sum(targets.values()) > size:
        source = max(targets, key=lambda s: (targets[s] - used[s], s))
        if targets[source] <= used[source]:
            break  # only forced picks left; coverage wins over size
        targets[source] -= 1
    return targets


def topic_caps(rows: list[dict], size: int) -> dict[str, int]:
    """Most rows each topic may get: its proportional share, but at least 1 (outliers: 5)."""
    total = len(rows)
    caps = {}
    for topic, n in Counter(r["model_topic"] for r in rows).items():
        floor = MIN_OUTLIERS if topic == OUTLIER_LABEL else 1
        caps[topic] = max(floor, math.ceil(size * n / total))
    return caps


def coverage_picks(rows: list[dict], rng: random.Random) -> list[dict]:
    """One random article per topic, plus up to MIN_OUTLIERS outliers."""
    by_topic: dict[str, list[dict]] = {}
    for row in rows:
        by_topic.setdefault(row["model_topic"], []).append(row)
    picks = []
    for topic in sorted(by_topic):
        wanted = MIN_OUTLIERS if topic == OUTLIER_LABEL else 1
        picks += rng.sample(by_topic[topic], min(wanted, len(by_topic[topic])))
    return picks


def take_until_full(candidates: list[dict], chosen: list[dict], caps: dict, limit: int) -> None:
    """Append candidates to `chosen` while `limit` allows and their topic is under its cap."""
    taken = {r["id"] for r in chosen}
    per_topic = Counter(r["model_topic"] for r in chosen)
    for row in candidates:
        if limit <= 0:
            return
        topic = row["model_topic"]
        if row["id"] in taken or per_topic[topic] >= caps[topic]:
            continue
        chosen.append(row)
        taken.add(row["id"])
        per_topic[topic] += 1
        limit -= 1


def stratified_sample(rows: list[dict], size: int, seed: int) -> list[dict]:
    """Cover every topic first, then fill each source up to its proportional quota.

    Topic coverage wins: with more topics than `size` allows, the sample is larger than size.
    """
    rng = random.Random(seed)
    if len(rows) <= size:
        chosen = list(rows)
    else:
        chosen = coverage_picks(rows, rng)
        caps = topic_caps(rows, size)
        quotas = proportional_quotas(Counter(r["source_name"] for r in rows), size)
        used = Counter(r["source_name"] for r in chosen)
        targets = source_targets(quotas, used, size)
        for source in sorted(targets):
            pool = [r for r in rows if r["source_name"] == source]
            rng.shuffle(pool)
            take_until_full(pool, chosen, caps, targets[source] - used[source])
        chosen_ids = {r["id"] for r in chosen}
        leftovers = [r for r in rows if r["id"] not in chosen_ids]
        rng.shuffle(leftovers)
        take_until_full(leftovers, chosen, caps, size - len(chosen))
    rng.shuffle(chosen)  # labelers should not see rows grouped by source or topic
    return chosen


def to_csv_row(article: dict) -> dict:
    """Model columns filled in, human columns left empty."""
    row = dict.fromkeys(COLUMNS, "")
    published = article["published_at"]
    confidence = article["model_confidence"]
    row.update(
        id=article["id"],
        title=" ".join((article["title"] or "").split()),
        url=article["url"],
        source_name=article["source_name"],
        published_at=f"{published[:16]} UTC" if published else "",
        model_topic=article["model_topic"],
        model_confidence="" if confidence is None else round(confidence, 4),
    )
    return row


def write_csv(rows: list[dict], out: Path) -> None:
    """UTF-8 with BOM so Excel shows accented characters correctly."""
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def print_summary(sample: list[dict], available: int, out: Path) -> None:
    """Counts only, never article text."""
    outliers = sum(r["model_topic"] == OUTLIER_LABEL for r in sample)
    print(f"Analyzed articles available: {available}")
    print(f"Exported: {len(sample)}")
    print("By source:", dict(Counter(r["source_name"] for r in sample).most_common()))
    print("By topic:", dict(Counter(r["model_topic"] for r in sample).most_common()))
    print(f"Outliers: {outliers}")
    print(f"File: {out}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=Path("local-data/ainis_eval.db"))
    parser.add_argument("--size", type=int, default=50)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=Path("local-data/corpus_to_label.csv"))
    args = parser.parse_args()
    if args.size < 1:
        parser.error("--size must be at least 1")
    return args


def main() -> None:
    args = parse_args()
    articles = load_articles(args.db)
    sample = stratified_sample(articles, args.size, args.seed)
    write_csv([to_csv_row(a) for a in sample], args.out)
    print_summary(sample, len(articles), args.out)


if __name__ == "__main__":
    main()
