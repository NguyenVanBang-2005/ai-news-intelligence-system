"""Score a labeled corpus CSV (from export_corpus.py) and compare two labelers.

Standard library only. Examples (from the repo root):
    python scripts/score_corpus.py local-data/labels_A.csv
    python scripts/score_corpus.py local-data/labels_A.csv local-data/labels_B.csv
"""

import argparse
import csv
from collections import Counter
from pathlib import Path

OUTLIER_LABEL = "Other / Outlier"
TOPIC_ANSWERS = ("yes", "no", "unsure")
SCORES = (1, 2, 3, 4, 5)


def read_rows(path: Path) -> list[dict]:
    """CSV rows as dicts; utf-8-sig also accepts files saved by Excel with a BOM."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def topic_answer(row: dict) -> str | None:
    """'yes' / 'no' / 'unsure', or None when empty or not one of those."""
    value = (row.get("topic_correct") or "").strip().lower()
    return value if value in TOPIC_ANSWERS else None


def summary_score(row: dict) -> int | None:
    """An integer 1-5, or None when empty or invalid."""
    value = (row.get("summary_score_1_to_5") or "").strip()
    return int(value) if value.isdigit() and int(value) in SCORES else None


def invalid_cells(rows: list[dict]) -> int:
    """Non-empty cells that are not valid labels (typos such as 'Yes!' or '6')."""
    bad = 0
    for row in rows:
        bad += bool((row.get("topic_correct") or "").strip()) and topic_answer(row) is None
        bad += bool((row.get("summary_score_1_to_5") or "").strip()) and summary_score(row) is None
    return bad


def summarize(rows: list[dict]) -> dict:
    """Headline numbers for one labeler's file."""
    answers = Counter(a for a in map(topic_answer, rows) if a)
    scores = [s for s in map(summary_score, rows) if s is not None]
    decided = answers["yes"] + answers["no"]
    outliers = sum((r.get("model_topic") or "") == OUTLIER_LABEL for r in rows)
    return {
        "rows": len(rows),
        "labeled": sum(topic_answer(r) is not None or summary_score(r) is not None for r in rows),
        "yes": answers["yes"],
        "no": answers["no"],
        "unsure": answers["unsure"],
        "topic_accuracy": answers["yes"] / decided if decided else None,
        "summary_mean": sum(scores) / len(scores) if scores else None,
        "summary_distribution": {score: scores.count(score) for score in SCORES},
        "outliers": outliers,
        "outlier_rate": outliers / len(rows) if rows else None,
        "invalid_cells": invalid_cells(rows),
    }


def paired_answers(first: list[dict], second: list[dict]) -> list[tuple[str, str]]:
    """topic_correct pairs for article ids that both labelers answered."""
    second_by_id = {r.get("id"): topic_answer(r) for r in second}
    pairs = []
    for row in first:
        mine, theirs = topic_answer(row), second_by_id.get(row.get("id"))
        if mine and theirs:
            pairs.append((mine, theirs))
    return pairs


def cohen_kappa(pairs: list[tuple[str, str]]) -> float | None:
    """Agreement corrected for chance; None when undefined (no pairs, or one shared label)."""
    if not pairs:
        return None
    total = len(pairs)
    observed = sum(a == b for a, b in pairs) / total
    first_counts = Counter(a for a, _ in pairs)
    second_counts = Counter(b for _, b in pairs)
    expected = sum(first_counts[k] * second_counts[k] for k in first_counts) / total**2
    if expected == 1:
        return None
    return (observed - expected) / (1 - expected)


def percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def print_summary(name: str, stats: dict) -> None:
    decided = stats["yes"] + stats["no"]
    mean = stats["summary_mean"]
    print(f"== {name}")
    print(f"Rows: {stats['rows']}, labeled: {stats['labeled']}")
    print(
        f"topic_correct = yes: {stats['yes']}/{decided} = {percent(stats['topic_accuracy'])}"
        f" (unsure excluded: {stats['unsure']})"
    )
    print("Summary score mean:", "n/a" if mean is None else f"{mean:.2f}")
    print("Summary score distribution:", stats["summary_distribution"])
    print(f"Outliers in sample: {stats['outliers']}/{stats['rows']} = "
          f"{percent(stats['outlier_rate'])}")
    if stats["invalid_cells"]:
        print(f"WARNING: {stats['invalid_cells']} cell(s) with invalid values were ignored")


def print_agreement(first: list[dict], second: list[dict]) -> None:
    pairs = paired_answers(first, second)
    agreed = sum(a == b for a, b in pairs)
    kappa = cohen_kappa(pairs)
    print("== Agreement on topic_correct (yes/no/unsure)")
    print(f"Articles answered by both: {len(pairs)}")
    print(f"Percent agreement: {agreed}/{len(pairs)} = "
          f"{percent(agreed / len(pairs) if pairs else None)}")
    print("Cohen's kappa:", "n/a" if kappa is None else f"{kappa:.3f}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("labels", type=Path, help="labeled CSV")
    parser.add_argument("second_labels", type=Path, nargs="?", help="second labeler's CSV")
    args = parser.parse_args()
    first = read_rows(args.labels)
    print_summary(args.labels.name, summarize(first))
    if args.second_labels:
        second = read_rows(args.second_labels)
        print_summary(args.second_labels.name, summarize(second))
        print_agreement(first, second)


if __name__ == "__main__":
    main()
