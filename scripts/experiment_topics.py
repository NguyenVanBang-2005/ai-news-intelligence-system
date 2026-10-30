"""Try HDBSCAN settings on the articles of a local SQLite database, without changing it.

Run from the repo root (settings, including EMBEDDING_MODEL_NAME, come from .env):
    python scripts/experiment_topics.py --db local-data/ainis_eval.db \
        --csv-out local-data/topic_experiment.csv \
        --table-out docs/evidence/topic_param_experiment.txt

Robustness gate (DATA-3): add --robustness to rerun configs with other UMAP seeds and
on random small batches instead of the grid; results go to --robustness-out.

Read-only: the database is opened with SQLite mode=ro, nothing is saved, and the
/ai/process job is never started. Embeddings are computed once and shared by all runs.

Reused from the app unchanged (same behaviour as an /ai/process job):
  - ArticleRepository.list_for_ai_processing (same articles, same order; force=True
    because the articles are already analyzed), build_document, encode_passages,
    get_embedding_model
  - TopicModelService._find_unique_documents, _create_topic_model (UMAP, CountVectorizer,
    KeyBERTInspired + MMR), _extract_confidences, _reduce_outliers (threshold from
    AI_OUTLIER_MIN_SIMILARITY), _merge_close_topics (reduce_topics when >= 3 topics),
    _topic_coherence (NPMI)
Mirrored, not reused:
  - The HDBSCAN model: _create_topic_model hard-codes it, so it is replaced on the built
    BERTopic object with the same arguments plus the min_cluster_size/min_samples tried.
  - The order of the steps in TopicModelService._cluster, copied so the topic counts
    before and after reduce_outliers can be recorded.
  - UMAP random_state: set on the UMAP object _create_topic_model built (the app uses 42).
"""

import argparse
import csv
import os
import platform
import random
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

OUTLIER_TOPIC = -1  # same as app.services.topic_model.OUTLIER_TOPIC

# The grid: every combination is run. None means the HDBSCAN default.
MIN_CLUSTER_SIZES = (3, 5, 8, 10)
MIN_SAMPLES = (1, 3, None)
CURRENT_CONFIG = (10, None)  # what the app uses for a 200-article batch

# Selection criteria, fixed before the experiment was run. They apply to the final
# clustering (after reduce_outliers and topic merging), i.e. what the app would store.
MIN_TOPICS, MAX_TOPICS = 5, 12
MAX_LARGEST_SHARE = 0.40
MAX_OUTLIER_SHARE = 0.25

# The real job on this database (275b6203...) gave 2 topics and 36 outliers.
REFERENCE_TOPICS, REFERENCE_OUTLIERS, OUTLIER_TOLERANCE = 2, 36, 5

# Robustness gate, fixed before it was run: the gate config passes when at least
# GATE_MIN_PASSING_SEEDS of the UMAP seeds give 5-12 topics, largest topic <= 40% and
# outliers <= 25%, and no small batch crashes. Small-batch numbers are only reported.
# Defaults are the DATA-3 run; DATA-3b passes --gate-min-samples 1 and new --seeds.
GATE_CONFIG = (8, 3)
ALT_CONFIG = (8, 1)
UMAP_SEEDS = (0, 1, 2, 3, 42)
GATE_MIN_PASSING_SEEDS = 4
SMALL_BATCH_SIZES = (50, 100)
SUBSET_SEEDS = (1, 2, 3)


@dataclass
class RunResult:
    min_cluster_size: int
    min_samples: int | None
    documents: int
    topics_before_outliers: int
    outliers_before: int
    topics_after_outliers: int
    outliers_after: int
    topics_final: int
    outliers_final: int
    largest_topic_size: int
    coherence: float | None
    keywords: dict[int, list[str]]
    seconds: float
    random_state: int = 42

    @property
    def outlier_share(self) -> float:
        return self.outliers_final / self.documents

    @property
    def largest_share(self) -> float:
        return self.largest_topic_size / self.documents


# ---------- pure logic (no ML imports; covered by tests) ----------


def grid() -> list[tuple[int, int | None]]:
    return [(size, samples) for size in MIN_CLUSTER_SIZES for samples in MIN_SAMPLES]


def count_topics(topics: list[int]) -> tuple[int, int]:
    """(number of topics without the outlier bucket, number of outlier documents)."""
    return len(set(topics) - {OUTLIER_TOPIC}), topics.count(OUTLIER_TOPIC)


def largest_topic_size(topics: list[int]) -> int:
    sizes = Counter(t for t in topics if t != OUTLIER_TOPIC)
    return max(sizes.values(), default=0)


def meets_criteria(result: RunResult) -> bool:
    return (
        MIN_TOPICS <= result.topics_final <= MAX_TOPICS
        and result.largest_share <= MAX_LARGEST_SHARE
        and result.outlier_share <= MAX_OUTLIER_SHARE
        and result.coherence is not None
    )


def pick_best(results: list[RunResult]) -> RunResult | None:
    """Highest coherence among the runs that meet the criteria; None if none does."""
    passing = [r for r in results if meets_criteria(r)]
    return max(passing, key=lambda r: r.coherence, default=None)


def reproduces_reference(result: RunResult) -> bool:
    """The current config should give about what the real job gave."""
    return (
        result.topics_final == REFERENCE_TOPICS
        and abs(result.outliers_final - REFERENCE_OUTLIERS) <= OUTLIER_TOLERANCE
    )


def samples_label(min_samples: int | None) -> str:
    return "default" if min_samples is None else str(min_samples)


def keywords_text(keywords: dict[int, list[str]]) -> str:
    return " | ".join(f"{topic}: {', '.join(words)}" for topic, words in keywords.items())


def to_csv_row(result: RunResult) -> dict:
    coherence = "" if result.coherence is None else result.coherence
    return {
        "min_cluster_size": result.min_cluster_size,
        "min_samples": samples_label(result.min_samples),
        "documents": result.documents,
        "topics_before_reduce_outliers": result.topics_before_outliers,
        "outliers_before_reduce_outliers": result.outliers_before,
        "topics_after_reduce_outliers": result.topics_after_outliers,
        "outliers_after_reduce_outliers": result.outliers_after,
        "topics_final": result.topics_final,
        "outliers_final": result.outliers_final,
        "outlier_pct": round(100 * result.outlier_share, 1),
        "largest_topic_pct": round(100 * result.largest_share, 1),
        "topic_coherence": coherence,
        "meets_criteria": "yes" if meets_criteria(result) else "no",
        "seconds": round(result.seconds, 1),
        "top5_keywords": keywords_text(result.keywords),
    }


def format_table(results: list[RunResult]) -> str:
    """One line per run; 'before -> after outliers -> final' for topic and outlier counts."""
    header = f"{'mcs':>3} {'min_s':>7} {'topics b>a>f':>13} {'outliers b>a>f':>15} " \
             f"{'outl%':>6} {'big%':>6} {'npmi':>7} {'ok':>3} {'sec':>5}"  # fmt: skip
    lines = [header, "-" * len(header)]
    for r in results:
        topics = f"{r.topics_before_outliers}>{r.topics_after_outliers}>{r.topics_final}"
        outliers = f"{r.outliers_before}>{r.outliers_after}>{r.outliers_final}"
        npmi = "n/a" if r.coherence is None else f"{r.coherence:.4f}"
        ok = "yes" if meets_criteria(r) else "no"
        lines.append(
            f"{r.min_cluster_size:>3} {samples_label(r.min_samples):>7} {topics:>13} "
            f"{outliers:>15} {100 * r.outlier_share:>6.1f} {100 * r.largest_share:>6.1f} "
            f"{npmi:>7} {ok:>3} {r.seconds:>5.1f}"
        )
    return "\n".join(lines)


def proposed_min_cluster_size(document_count: int) -> int:
    """Formula proposed in DATA-3 for the app: like today's, but capped at 8 instead of 10."""
    return max(2, min(8, document_count // 5))


def proposed_min_samples(min_cluster_size: int, cap: int = 3) -> int:
    """DATA-3 proposed min(3, mcs); DATA-3b uses cap=1, i.e. always 1."""
    return min(cap, min_cluster_size)


def meets_gate_criteria(result: RunResult) -> bool:
    """The gate's per-run test: same bounds as the selection criteria, no NPMI condition."""
    return (
        MIN_TOPICS <= result.topics_final <= MAX_TOPICS
        and result.largest_share <= MAX_LARGEST_SHARE
        and result.outlier_share <= MAX_OUTLIER_SHARE
    )


def gate_passes(seed_results: list[RunResult], small_batch_errors: list[str]) -> bool:
    passing = sum(meets_gate_criteria(r) for r in seed_results)
    return passing >= GATE_MIN_PASSING_SEEDS and not small_batch_errors


def subset_indices(total: int, size: int, seed: int) -> list[int]:
    """A reproducible random subset, kept in the original (processing) order."""
    return sorted(random.Random(seed).sample(range(total), size))


def metrics_cells(result: RunResult) -> str:
    npmi = "n/a" if result.coherence is None else f"{result.coherence:.4f}"
    return (f"{result.topics_final:>6} {100 * result.outlier_share:>6.1f} "
            f"{100 * result.largest_share:>6.1f} {npmi:>7}")  # fmt: skip


# ---------- the experiment (needs the ML stack and the embedding model) ----------


def load_documents(db_path: Path) -> tuple[list[str], list]:
    """The documents an /ai/process job would build, and their cached embeddings."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    import app.db.base  # noqa: F401  (registers all models)
    from app.core.config import settings
    from app.repositories.article import ArticleRepository
    from app.services.embeddings import build_document, embedding_key

    engine = create_engine(read_only_url(db_path))
    with Session(engine) as db:
        articles = ArticleRepository(db).list_for_ai_processing(
            limit=settings.ai_batch_size, force=True
        )
        documents = [build_document(title=a.title, content=a.content) for a in articles]
        cached = [a.cached_embedding(embedding_key(d)) for a, d in zip(articles, documents,
                                                                         strict=True)]  # fmt: skip
    engine.dispose()
    return documents, cached


def read_only_url(db_path: Path) -> str:
    if not db_path.is_file():
        raise FileNotFoundError(f"Database not found: {db_path}")
    return f"sqlite:///file:{db_path.resolve().as_posix()}?mode=ro&uri=true"


def embed_unique(documents: list[str], cached: list):
    """Embed once with the app's model and prefix, then drop semantic duplicates like the app."""
    import numpy as np

    from app.core.config import settings
    from app.services.embeddings import encode_passages, get_embedding_model
    from app.services.topic_model import TopicModelService

    embeddings = encode_passages(get_embedding_model(), documents).astype(np.float32)
    usable = [(e, c) for e, c in zip(embeddings, cached, strict=True) if c is not None]
    drift = max((float(np.abs(e - c).max()) for e, c in usable), default=None)
    unique, _ = TopicModelService._find_unique_documents(
        embeddings, threshold=settings.duplicate_similarity_threshold
    )
    return [documents[i] for i in unique], embeddings[unique], len(usable), drift


def run_config(
    documents: list[str], embeddings, min_cluster_size: int, min_samples, random_state: int = 42
) -> RunResult:
    """One clustering, mirroring TopicModelService._cluster step by step."""
    from hdbscan import HDBSCAN

    from app.services.topic_model import Clustering, TopicModelService

    start = time.perf_counter()
    model = TopicModelService._create_topic_model(document_count=len(documents))
    model.umap_model.random_state = random_state
    model.hdbscan_model = HDBSCAN(
        min_cluster_size=min_cluster_size, min_samples=min_samples, metric="euclidean",
        cluster_selection_method="eom", prediction_data=True,
    )  # fmt: skip
    raw, probabilities = model.fit_transform(documents, embeddings)
    before = [int(t) for t in raw]
    confidences, method = TopicModelService._extract_confidences(
        probabilities, document_count=len(documents)
    )
    after = [int(t) for t in TopicModelService._reduce_outliers(
        model, documents, embeddings, list(before))]  # fmt: skip
    final = [int(t) for t in TopicModelService._merge_close_topics(model, documents, after)]
    coherence = TopicModelService._topic_coherence(
        Clustering(final, confidences, method, model), documents
    )
    seconds = time.perf_counter() - start
    keywords = {t: [w for w, _ in model.get_topic(t)[:5]] for t in sorted(set(final) - {-1})}
    return RunResult(min_cluster_size, min_samples, len(documents), *count_topics(before),
                     *count_topics(after), *count_topics(final), largest_topic_size(final),
                     coherence, keywords, seconds, random_state)  # fmt: skip


def run_seeds(documents: list[str], embeddings, configs, seeds) -> list[RunResult]:
    """Every (min_cluster_size, min_samples) config with every UMAP seed, on all documents."""
    results = []
    for size, samples in configs:
        for seed in seeds:
            result = run_config(documents, embeddings, size, samples, random_state=seed)
            print(f"({size},{samples}) seed={seed}: {result.topics_final} topics", flush=True)
            results.append(result)
    return results


def run_small_batches(documents: list[str], embeddings, samples_cap: int = 3):
    """Random subsets with the proposed formula; crashes are collected, not raised."""
    rows, errors = [], []
    for size in SMALL_BATCH_SIZES:
        cluster_size = proposed_min_cluster_size(size)
        samples = proposed_min_samples(cluster_size, samples_cap)
        for seed in SUBSET_SEEDS:
            picked = subset_indices(len(documents), size, seed)
            try:
                result = run_config([documents[i] for i in picked], embeddings[picked],
                                    cluster_size, samples)  # fmt: skip
            except Exception as exc:  # a crash is a result here: it fails the gate
                errors.append(f"n={size} subset_seed={seed}: {type(exc).__name__}: {exc}")
                continue
            print(f"n={size} subset_seed={seed}: {result.topics_final} topics", flush=True)
            rows.append((size, seed, result))
    return rows, errors


# ---------- output ----------


def write_csv(results: list[RunResult], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = [to_csv_row(r) for r in results]
    with out.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, check=True).stdout.strip()  # fmt: skip
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def run_info(title: str, model_name: str, documents: int, cache_note: str) -> list[str]:
    """Date, commit, Python, command and model: the first lines of every evidence file."""
    return [
        title,
        f"Date (UTC): {datetime.now(UTC):%Y-%m-%d %H:%M}",
        f"Commit: {git_commit()}",
        f"Python: {platform.python_version()}",
        "Command: python " + " ".join(Path(a).as_posix() for a in sys.argv),
        f"Embedding model: {model_name} (HF_HUB_OFFLINE=1); documents: {documents}",
        f"Embedding check against the vectors cached by the real job: {cache_note}",
    ]


def report_header(model_name: str, documents: int, cache_note: str) -> list[str]:
    title = "Topic parameter experiment (HDBSCAN grid on the DATA-1 corpus, read-only)"
    return run_info(title, model_name, documents, cache_note) + [
        f"Criteria (fixed beforehand, on final values): {MIN_TOPICS}-{MAX_TOPICS} topics, "
        f"largest topic <= {MAX_LARGEST_SHARE:.0%}, outliers <= {MAX_OUTLIER_SHARE:.0%}; "
        "best = highest topic_coherence (NPMI)",
        "Columns: topics/outliers as before reduce_outliers > after > final (after merge);",
        "         outl% and big% are shares of all documents (final).",
        "",
    ]


def report_body(results: list[RunResult]) -> list[str]:
    best = pick_best(results)
    lines = [format_table(results), "", "Top 5 keywords per final topic"]
    for r in results:
        lines.append(f"  mcs={r.min_cluster_size} min_samples={samples_label(r.min_samples)}")
        lines += [f"    {topic}: {', '.join(words)}" for topic, words in r.keywords.items()]
    lines.append("")
    if best is None:
        lines.append("Result: no configuration meets the criteria.")
    else:
        lines.append(f"Result: best = min_cluster_size={best.min_cluster_size}, "
                     f"min_samples={samples_label(best.min_samples)} "
                     f"(coherence {best.coherence:.4f})")  # fmt: skip
    return lines


def seed_lines(seed_results: list[RunResult]) -> list[str]:
    lines = ["UMAP seeds, all documents (ok = 5-12 topics, big <= 40%, outliers <= 25%)",
             f"{'config':>7} {'seed':>4} {'topics':>6} {'outl%':>6} {'big%':>6} {'npmi':>7} ok"]
    for r in seed_results:
        config = f"({r.min_cluster_size},{r.min_samples})"
        ok = "yes" if meets_gate_criteria(r) else "no"
        lines.append(f"{config:>7} {r.random_state:>4} {metrics_cells(r)} {ok}")
    lines += ["", "Top 5 keywords per topic"]
    for r in seed_results:
        lines.append(f"  ({r.min_cluster_size},{r.min_samples}) seed {r.random_state}")
        lines += [f"    {topic}: {', '.join(words)}" for topic, words in r.keywords.items()]
    return lines


def batch_lines(batch_rows: list, errors: list[str]) -> list[str]:
    lines = ["Small batches, proposed formula, UMAP seed 42 (reported only)",
             f"{'n':>4} {'subset':>6} {'mcs':>3} {'min_s':>5} {'topics':>6} {'outl%':>6} "
             f"{'big%':>6} {'npmi':>7}"]  # fmt: skip
    for size, seed, r in batch_rows:
        lines.append(f"{size:>4} {seed:>6} {r.min_cluster_size:>3} {r.min_samples:>5} "
                     f"{metrics_cells(r)}")  # fmt: skip
    lines.append("Small-batch errors: " + ("; ".join(errors) if errors else "none"))
    return lines


def robustness_lines(seed_results, batch_rows, errors, gate_config=GATE_CONFIG):
    """Seed table, small-batch table and the gate verdict."""
    gate_runs = [r for r in seed_results if (r.min_cluster_size, r.min_samples) == gate_config]
    passing = sum(meets_gate_criteria(r) for r in gate_runs)
    verdict = "PASSES" if gate_passes(gate_runs, errors) else "DOES NOT PASS"
    return (
        seed_lines(seed_results)
        + ["", f"{gate_config}: {passing}/{len(gate_runs)} seeds meet the criteria "
               f"(needed: {GATE_MIN_PASSING_SEEDS})", ""]  # fmt: skip
        + batch_lines(batch_rows, errors)
        + ["", f"Gate verdict: {gate_config} {verdict}"]
    )


def write_lines(out: Path, lines: list[str], append: bool = False) -> None:
    """Write the lines to `out`; with append, add them after a blank line instead."""
    out.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(lines) + "\n"
    if append and out.exists():
        text = out.read_text(encoding="utf-8") + "\n" + text
    out.write_text(text, encoding="utf-8")


def parse_seeds(text: str) -> list[int]:
    return [int(part) for part in text.split(",") if part.strip()]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=Path("local-data/ainis_eval.db"))
    parser.add_argument("--csv-out", type=Path, default=Path("local-data/topic_experiment.csv"))
    parser.add_argument("--table-out", type=Path,
                        default=Path("docs/evidence/topic_param_experiment.txt"))  # fmt: skip
    parser.add_argument("--robustness", action="store_true",
                        help="run the DATA-3 robustness gate instead of the grid")  # fmt: skip
    parser.add_argument("--robustness-out", type=Path,
                        default=Path("docs/evidence/topic_robustness.txt"))  # fmt: skip
    parser.add_argument("--gate-min-samples", type=int, default=GATE_CONFIG[1],
                        help="min_samples of the gate config (min_cluster_size is 8)")
    parser.add_argument("--compare-min-samples", default=str(ALT_CONFIG[1]),
                        help="min_samples of a comparison config, or 'none' for no comparison")
    parser.add_argument("--seeds", type=parse_seeds, default=list(UMAP_SEEDS),
                        help="UMAP seeds, e.g. 5,6,7,8,9")
    parser.add_argument("--append", action="store_true",
                        help="add a section to --robustness-out instead of replacing it")
    parser.add_argument("--section", default="Topic robustness gate (DATA-3, read-only)",
                        help="title line of the robustness section")
    return parser.parse_args()


def run_grid(documents: list[str], embeddings) -> list[RunResult] | None:
    """Current config first: stop (None) if it does not reproduce the real job."""
    configs = [CURRENT_CONFIG] + [c for c in grid() if c != CURRENT_CONFIG]
    results = []
    for size, samples in configs:
        result = run_config(documents, embeddings, size, samples)
        print(f"mcs={size} min_samples={samples_label(samples)}: {result.topics_final} topics, "
              f"{result.outliers_final} outliers, {result.seconds:.1f}s", flush=True)  # fmt: skip
        if (size, samples) == CURRENT_CONFIG and not reproduces_reference(result):
            print("STOP: the current config does not reproduce the real job "
                  f"({REFERENCE_TOPICS} topics, {REFERENCE_OUTLIERS} outliers).")  # fmt: skip
            return None
        results.append(result)
    return sorted(results, key=lambda r: (r.min_cluster_size, r.min_samples or 99))


def run_robustness(args: argparse.Namespace, documents: list[str], embeddings, info) -> None:
    """Seeds on all documents, then small batches; the verdict goes to --robustness-out."""
    gate_config = (GATE_CONFIG[0], args.gate_min_samples)
    configs = [gate_config]
    if args.compare_min_samples.lower() != "none":
        configs.append((GATE_CONFIG[0], int(args.compare_min_samples)))
    seed_results = run_seeds(documents, embeddings, configs, args.seeds)
    batch_rows, errors = run_small_batches(documents, embeddings, args.gate_min_samples)
    lines = robustness_lines(seed_results, batch_rows, errors, gate_config)
    write_lines(args.robustness_out, info + [""] + lines, append=args.append)
    print("\n".join(lines))


def main() -> None:
    args = parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `app` importable
    os.environ["HF_HUB_OFFLINE"] = "1"  # never download a model
    os.environ["DATABASE_URL"] = read_only_url(args.db)  # app engine also read-only
    from app.core.config import settings

    documents, cached = load_documents(args.db)
    documents, embeddings, compared, drift = embed_unique(documents, cached)
    cache_note = f"{compared} compared, max abs difference {drift}"
    print(f"Documents: {len(documents)}; {cache_note}", flush=True)
    model_name = settings.embedding_model_name
    if args.robustness:
        info = run_info(args.section, model_name, len(documents), cache_note)
        run_robustness(args, documents, embeddings, info)
        return
    results = run_grid(documents, embeddings)
    if results is None:
        sys.exit(1)
    write_csv(results, args.csv_out)
    header = report_header(model_name, len(documents), cache_note)
    write_lines(args.table_out, header + report_body(results))
    print("\n".join(report_body(results)))


if __name__ == "__main__":
    main()
