"""Try HDBSCAN settings on the articles of a local SQLite database, without changing it.

Run from the repo root (settings, including EMBEDDING_MODEL_NAME, come from .env):
    python scripts/experiment_topics.py --db local-data/ainis_eval.db \
        --csv-out local-data/topic_experiment.csv \
        --table-out docs/evidence/topic_param_experiment.txt

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
"""

import argparse
import csv
import os
import platform
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


def run_config(documents: list[str], embeddings, min_cluster_size: int, min_samples) -> RunResult:
    """One clustering, mirroring TopicModelService._cluster step by step."""
    from hdbscan import HDBSCAN

    from app.services.topic_model import Clustering, TopicModelService

    start = time.perf_counter()
    model = TopicModelService._create_topic_model(document_count=len(documents))
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
                     coherence, keywords, seconds)  # fmt: skip


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


def report_header(model_name: str, documents: int, cache_note: str) -> list[str]:
    return [
        "Topic parameter experiment (HDBSCAN grid on the DATA-1 corpus, read-only)",
        f"Date (UTC): {datetime.now(UTC):%Y-%m-%d %H:%M}",
        f"Commit: {git_commit()}",
        f"Python: {platform.python_version()}",
        "Command: python " + " ".join(Path(a).as_posix() for a in sys.argv),
        f"Embedding model: {model_name} (HF_HUB_OFFLINE=1); documents: {documents}",
        f"Embedding check against the vectors cached by the real job: {cache_note}",
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=Path("local-data/ainis_eval.db"))
    parser.add_argument("--csv-out", type=Path, default=Path("local-data/topic_experiment.csv"))
    parser.add_argument("--table-out", type=Path,
                        default=Path("docs/evidence/topic_param_experiment.txt"))  # fmt: skip
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
    results = run_grid(documents, embeddings)
    if results is None:
        sys.exit(1)
    write_csv(results, args.csv_out)
    lines = report_header(settings.embedding_model_name, len(documents), cache_note)
    args.table_out.parent.mkdir(parents=True, exist_ok=True)
    args.table_out.write_text("\n".join(lines + report_body(results)) + "\n", encoding="utf-8")
    print("\n".join(report_body(results)))


if __name__ == "__main__":
    main()
