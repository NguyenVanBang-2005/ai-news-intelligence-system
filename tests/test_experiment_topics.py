"""Pure logic of the topic parameter experiment: grid, counts and selection (no model)."""

import csv
from pathlib import Path

from scripts.experiment_topics import (
    CURRENT_CONFIG,
    RunResult,
    count_topics,
    format_table,
    gate_passes,
    grid,
    largest_topic_size,
    meets_criteria,
    meets_gate_criteria,
    parse_seeds,
    pick_best,
    proposed_min_cluster_size,
    proposed_min_samples,
    reproduces_reference,
    subset_indices,
    write_csv,
    write_lines,
)


def result(topics=7, outliers=20, largest=60, coherence=0.1, size=8, samples=3) -> RunResult:
    """A fake run over 200 documents; counts are final values."""
    return RunResult(size, samples, 200, topics, outliers, topics, outliers, topics, outliers,
                     largest, coherence, {0: ["a", "b"]}, 1.0)  # fmt: skip


def test_grid_has_all_twelve_configs_including_current() -> None:
    configs = grid()
    assert len(configs) == 12 == len(set(configs))
    assert CURRENT_CONFIG in configs


def test_count_topics_and_largest_ignore_outliers() -> None:
    topics = [-1, -1, 0, 0, 0, 1, 2]
    assert count_topics(topics) == (3, 2)
    assert largest_topic_size(topics) == 3
    assert largest_topic_size([-1, -1]) == 0


def test_criteria_bounds_are_inclusive() -> None:
    assert meets_criteria(result(topics=5, outliers=50, largest=80))  # 25% and 40%
    assert meets_criteria(result(topics=12))
    assert not meets_criteria(result(topics=4))
    assert not meets_criteria(result(topics=13))
    assert not meets_criteria(result(outliers=51))
    assert not meets_criteria(result(largest=81))
    assert not meets_criteria(result(coherence=None))


def test_pick_best_takes_highest_coherence_among_passing_only() -> None:
    failing_but_coherent = result(topics=2, coherence=0.9)
    low, high = result(coherence=-0.2), result(coherence=0.05)
    assert pick_best([failing_but_coherent, low, high]) is high
    assert pick_best([failing_but_coherent]) is None


def test_reproduces_reference_tolerates_small_outlier_drift() -> None:
    assert reproduces_reference(result(topics=2, outliers=36))
    assert reproduces_reference(result(topics=2, outliers=41))
    assert not reproduces_reference(result(topics=2, outliers=42))
    assert not reproduces_reference(result(topics=3, outliers=36))


def test_csv_and_table_outputs(tmp_path: Path) -> None:
    runs = [result(), result(samples=None, coherence=None)]
    out = tmp_path / "exp.csv"
    write_csv(runs, out)
    with out.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [r["min_samples"] for r in rows] == ["3", "default"]
    assert rows[0]["meets_criteria"] == "yes" and rows[1]["topic_coherence"] == ""
    assert rows[0]["largest_topic_pct"] == "30.0"
    table = format_table(runs)
    assert "7>7>7" in table and "n/a" in table


def test_proposed_formula_for_batch_sizes() -> None:
    sizes = {n: proposed_min_cluster_size(n) for n in (10, 30, 50, 100, 200)}
    assert sizes == {10: 2, 30: 6, 50: 8, 100: 8, 200: 8}
    assert [proposed_min_samples(s) for s in (2, 3, 8)] == [2, 3, 3]


def test_gate_needs_four_passing_seeds_and_no_crash() -> None:
    good, bad = result(), result(topics=3)
    assert not meets_gate_criteria(bad)
    assert meets_gate_criteria(result(coherence=None))  # the gate has no NPMI condition
    assert gate_passes([good] * 4 + [bad], [])
    assert not gate_passes([good] * 3 + [bad] * 2, [])
    assert not gate_passes([good] * 5, ["n=50 subset_seed=1: ValueError: boom"])


def test_subset_indices_are_reproducible_sorted_and_unique() -> None:
    first = subset_indices(200, 50, seed=1)
    assert first == subset_indices(200, 50, seed=1)
    assert first == sorted(set(first)) and len(first) == 50
    assert first != subset_indices(200, 50, seed=2)


def test_min_samples_cap_for_data_3b() -> None:
    assert [proposed_min_samples(s, cap=1) for s in (2, 8)] == [1, 1]


def test_parse_seeds_and_append(tmp_path: Path) -> None:
    assert parse_seeds("5,6, 7,") == [5, 6, 7]
    out = tmp_path / "robustness.txt"
    write_lines(out, ["DATA-3"])
    write_lines(out, ["DATA-3b"], append=True)
    assert out.read_text(encoding="utf-8") == "DATA-3\n\nDATA-3b\n"
