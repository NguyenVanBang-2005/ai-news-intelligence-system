"""Scoring script for labeled corpus CSVs: uses small fake CSVs only (no database)."""

import csv
import sys
from pathlib import Path

import pytest

from scripts.export_corpus import COLUMNS
from scripts.score_corpus import (
    OUTLIER_LABEL,
    cohen_kappa,
    main,
    paired_answers,
    read_rows,
    summarize,
)


def write_labels(path: Path, labels: list[tuple[str, str, str]]) -> Path:
    """labels: (model_topic, topic_correct, summary_score) per article; ids are 1..n."""
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        for index, (topic, correct, score) in enumerate(labels, start=1):
            row = dict.fromkeys(COLUMNS, "")
            row.update(id=index, model_topic=topic, topic_correct=correct,
                       summary_score_1_to_5=score)  # fmt: skip
            writer.writerow(row)
    return path


def test_summary_excludes_unsure_and_counts_outliers(tmp_path: Path) -> None:
    labels = [("A", "yes", "5"), ("A", "Yes ", "3"), ("A", "no", "1"),
              ("A", "unsure", ""), (OUTLIER_LABEL, "", ""), (OUTLIER_LABEL, "no", "4")]  # fmt: skip
    stats = summarize(read_rows(write_labels(tmp_path / "a.csv", labels)))
    assert stats["labeled"] == 5
    assert (stats["yes"], stats["no"], stats["unsure"]) == (2, 2, 1)
    assert stats["topic_accuracy"] == 0.5
    assert stats["summary_mean"] == pytest.approx(13 / 4)
    assert stats["summary_distribution"] == {1: 1, 2: 0, 3: 1, 4: 1, 5: 1}
    assert stats["outlier_rate"] == pytest.approx(2 / 6)


def test_invalid_values_are_ignored_and_reported(tmp_path: Path) -> None:
    labels = [("A", "maybe", "6"), ("A", "yes", "x"), ("A", "no", "2")]
    stats = summarize(read_rows(write_labels(tmp_path / "a.csv", labels)))
    assert stats["invalid_cells"] == 3
    assert stats["topic_accuracy"] == 0.5
    assert stats["summary_mean"] == 2


def test_empty_file_gives_no_rates(tmp_path: Path) -> None:
    stats = summarize(read_rows(write_labels(tmp_path / "a.csv", [("A", "", "")])))
    assert stats["labeled"] == 0
    assert stats["topic_accuracy"] is None and stats["summary_mean"] is None


def test_kappa_known_value() -> None:
    pairs = [("yes", "yes"), ("yes", "no"), ("no", "no"), ("no", "no")]
    assert cohen_kappa(pairs) == pytest.approx(0.5)  # observed 0.75, chance 0.5


def test_kappa_perfect_and_undefined() -> None:
    assert cohen_kappa([("yes", "yes"), ("no", "no")]) == pytest.approx(1.0)
    assert cohen_kappa([("yes", "yes"), ("yes", "yes")]) is None
    assert cohen_kappa([]) is None


def test_pairs_match_by_id_and_skip_blanks(tmp_path: Path) -> None:
    first = read_rows(write_labels(tmp_path / "a.csv", [("A", "yes", ""), ("A", "no", ""),
                                                         ("A", "", "")]))  # fmt: skip
    second = read_rows(write_labels(tmp_path / "b.csv", [("A", "yes", ""), ("A", "yes", ""),
                                                          ("A", "no", "")]))  # fmt: skip
    assert paired_answers(first, second) == [("yes", "yes"), ("no", "yes")]


def test_cli_prints_agreement_for_two_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    first = write_labels(tmp_path / "a.csv", [("A", "yes", "4"), ("A", "no", "2")])
    second = write_labels(tmp_path / "b.csv", [("A", "yes", "5"), ("A", "yes", "2")])
    monkeypatch.setattr(sys, "argv", ["score_corpus.py", str(first), str(second)])
    main()
    output = capsys.readouterr().out
    assert "Articles answered by both: 2" in output
    assert "Percent agreement: 1/2 = 50.0%" in output
    assert "Cohen's kappa: 0.000" in output
