"""POST /api/v1/ai/process: contract, persistence and failure behaviour.

MOCK NOTICE: the sentence-transformer is replaced by `FakeEmbedder` (deterministic vectors,
one direction per synthetic topic), so these tests never download a model. UMAP, HDBSCAN,
BERTopic, the repository and the database are real. They verify validity, ID mapping,
storage and error handling. Real-model behaviour is covered by the Docker acceptance run
(tests/e2e/, docs/e2e-acceptance.md). Exact labels / topic counts are deliberately not asserted.
"""

import re
import zlib
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.orm.session import Session as SASession

try:
    import app.services.topic_model as topic_model
except (ImportError, OSError) as exc:  # optional ML stack missing or blocked by the OS
    pytest.skip(f"AI dependencies unavailable: {exc}", allow_module_level=True)

from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS

from app.models.article import Article
from app.models.source import Source
from app.repositories.article import ArticleRepository

OUTLIER = "Other / Outlier"
START = datetime(2026, 9, 1, tzinfo=UTC)


class FakeEmbedder:
    """Maps 'G<k>' in the text to axis k plus small deterministic noise, L2-normalised."""

    def encode(self, documents: list[str], **kwargs: object) -> np.ndarray:
        vectors = []
        for doc in documents:
            vec = np.zeros(16)
            vec[int(re.search(r"G(\d+)", doc).group(1))] = 1.0
            noise = np.random.default_rng(zlib.crc32(doc.encode())).normal(size=16) * 0.2
            vec = vec + noise
            vectors.append(vec / np.linalg.norm(vec))
        return np.asarray(vectors)


@pytest.fixture(autouse=True)
def fake_model(monkeypatch: pytest.MonkeyPatch) -> FakeEmbedder:
    embedder = FakeEmbedder()
    monkeypatch.setattr(topic_model, "get_embedding_model", lambda: embedder)
    return embedder


def seed(
    engine: Engine,
    *,
    groups: int = 3,
    per_group: int = 5,
    duplicates_of: tuple[int, ...] = (),
    empty: int = 0,
    identical: int = 0,
) -> dict[str, list[int]]:
    """Insert articles; returns ids by kind. created_at increases with insertion order."""
    ids: dict[str, list[int]] = {"usable": [], "empty": [], "dup": []}
    with Session(engine) as db:
        source = Source(name="Seed", feed_url="https://seed.example/rss.xml")
        db.add(source)
        db.flush()
        minute = 0

        def add(title: str, url: str, content: str, status: str) -> int:
            nonlocal minute
            minute += 1
            article = Article(
                source_id=source.id, title=title, url=url, content=content, status=status,
                created_at=START + timedelta(minutes=minute),
            )
            db.add(article)
            db.flush()
            return article.id

        usable_texts = []
        for group in range(groups):
            for i in range(per_group):
                title = f"Headline G{group} number {i}"
                content = f"G{group} story {i} about subject{group} with the and of details"
                usable_texts.append((title, content))
                ids["usable"].append(add(title, f"https://seed.example/{group}-{i}",
                                         content, "analyzed"))
        for n, original in enumerate(duplicates_of):
            title, content = usable_texts[original]
            ids["dup"].append(add(title, f"https://seed.example/dup-{n}", content, "analyzed"))
        for n in range(identical):
            ids["usable"].append(add("Same G0 headline", f"https://seed.example/same-{n}",
                                     "G0 exactly the same body", "analyzed"))
        for n in range(empty):
            ids["empty"].append(add(f"No body {n}", f"https://seed.example/empty-{n}", "",
                                    "missing_content"))
        db.commit()
    return ids


def rows(engine: Engine) -> dict[int, Article]:
    with Session(engine) as db:
        return {a.id: a for a in db.scalars(select(Article))}


def process(client: TestClient, **body: object):
    return client.post("/api/v1/ai/process", json=body)


def test_below_threshold_is_409_before_the_model_is_touched(
    client: TestClient, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    def must_not_load() -> None:
        raise AssertionError("model must not be loaded for a batch that is too small")

    monkeypatch.setattr(topic_model, "get_embedding_model", must_not_load)
    seed(engine, groups=1, per_group=5, empty=3)

    response = process(client)

    assert response.status_code == 409
    assert "at least 10" in response.json()["detail"]
    assert {a.status for a in rows(engine).values()} == {"analyzed", "missing_content"}
    assert all(a.topic is None for a in rows(engine).values())


def test_exact_threshold_saves_valid_results_to_the_right_articles(
    client: TestClient, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = seed(engine, groups=2, per_group=5, empty=2)
    saved: list[tuple[int, str, float]] = []
    original = ArticleRepository.save_ai_results

    def spy(self: ArticleRepository, results: list[tuple[int, str, float]]) -> None:
        saved.extend(results)
        original(self, results)

    monkeypatch.setattr(ArticleRepository, "save_ai_results", spy)

    response = process(client)

    assert response.status_code == 200
    body = response.json()
    assert body["documents_received"] == body["articles_updated"] == 10
    assert body["unique_documents"] + body["semantic_duplicates"] == 10
    assert sorted(i for i, _, _ in saved) == sorted(ids["usable"])  # no empty/foreign IDs
    stored = rows(engine)
    for article_id, topic, confidence in saved:
        assert 0 < len(topic) <= 80
        assert 0.0 <= confidence <= 1.0
        assert (stored[article_id].topic, stored[article_id].confidence) == (topic, confidence)
        assert stored[article_id].status == "ai_analyzed"
    for article_id in ids["empty"]:  # not eligible: never marked as analysed
        assert stored[article_id].status == "missing_content"
        assert stored[article_id].topic is None and stored[article_id].confidence is None

    page = client.get("/api/v1/articles", params={"status": "ai_analyzed", "limit": 100}).json()
    assert page["total"] == 10
    assert {(a["id"], a["topic"], a["confidence"]) for a in page["items"]} == set(saved)
    trending = client.get("/api/v1/topics/trending").json()
    assert sum(t["article_count"] for t in trending) == 10


def test_semantic_duplicates_share_the_canonical_articles_result(
    client: TestClient, engine: Engine
) -> None:
    ids = seed(engine, groups=3, per_group=5, duplicates_of=(0, 7))

    body = process(client).json()

    assert body["documents_received"] == body["articles_updated"] == 17
    assert body["semantic_duplicates"] == 2
    assert body["unique_documents"] == 15
    stored = rows(engine)
    for dup_id, original_id in zip(ids["dup"], (ids["usable"][0], ids["usable"][7]), strict=True):
        assert stored[dup_id].status == "ai_analyzed"
        assert (stored[dup_id].topic, stored[dup_id].confidence) == (
            stored[original_id].topic, stored[original_id].confidence)


def test_force_false_skips_analyzed_and_force_true_with_limit_takes_oldest(
    client: TestClient, engine: Engine
) -> None:
    ids = seed(engine, groups=3, per_group=5)
    assert process(client).status_code == 200
    with Session(engine) as db:  # sentinel shows exactly which rows a later run rewrites
        for article in db.scalars(select(Article)):
            article.topic, article.confidence = "SENTINEL", -1.0
        db.commit()

    again = process(client)
    assert again.status_code == 409  # nothing eligible without force
    assert {a.topic for a in rows(engine).values()} == {"SENTINEL"}

    forced = process(client, force=True, limit=10)
    assert forced.status_code == 200
    assert forced.json()["articles_updated"] == 10
    rewritten = {i for i, a in rows(engine).items() if a.topic != "SENTINEL"}
    assert rewritten == set(ids["usable"][:10])  # the 10 oldest by created_at


def test_identical_documents_are_409_and_not_marked_analysed(
    client: TestClient, engine: Engine
) -> None:
    seed(engine, groups=0, identical=12)

    response = process(client)

    assert response.status_code == 409
    assert "Unique documents: 1" in response.json()["detail"]
    assert {a.status for a in rows(engine).values()} == {"analyzed"}
    assert all(a.topic is None for a in rows(engine).values())


def test_no_clusters_found_is_a_valid_run_not_an_error(
    client: TestClient, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Documents CURRENT behaviour: when HDBSCAN finds no cluster every article is stored as
    'Other / Outlier' with confidence 0.0 and status ai_analyzed (so it is skipped unless
    force=true). Whether that status is desirable is an open contract question."""
    from hdbscan import HDBSCAN

    original = topic_model.TopicModelService._create_topic_model

    def no_cluster_model(document_count: int):
        model = original(document_count)
        model.hdbscan_model = HDBSCAN(
            min_cluster_size=document_count, metric="euclidean", prediction_data=True
        )
        return model

    monkeypatch.setattr(
        topic_model.TopicModelService, "_create_topic_model", staticmethod(no_cluster_model)
    )
    seed(engine, groups=2, per_group=6)

    response = process(client)

    assert response.status_code == 200
    assert response.json()["topics_created"] == 0
    for article in rows(engine).values():
        assert (article.topic, article.confidence, article.status) == (OUTLIER, 0.0, "ai_analyzed")


def test_model_failure_is_503_without_leaking_details_and_crud_still_works(
    client: TestClient, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken() -> None:
        raise OSError("401 for https://huggingface.co/secret-org/model token=hf_SECRET")

    monkeypatch.setattr(topic_model, "get_embedding_model", broken)
    seed(engine, groups=2, per_group=5)

    response = process(client)

    assert response.status_code == 503
    assert "model could not be loaded" in response.json()["detail"]
    assert "hf_SECRET" not in response.text and "huggingface" not in response.text
    assert {a.status for a in rows(engine).values()} == {"analyzed"}
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/sources").status_code == 200
    assert client.get("/api/v1/articles").json()["total"] == 10


def test_too_small_batch_is_409_even_when_the_model_cannot_load(
    client: TestClient, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: the model used to be loaded before counting articles, so an empty or
    undersized batch failed with 500 (after a slow download attempt) instead of 409."""

    def broken() -> None:
        raise OSError("no network")

    monkeypatch.setattr(topic_model, "get_embedding_model", broken)

    assert process(client).status_code == 409  # empty database
    seed(engine, groups=1, per_group=3)
    assert process(client).status_code == 409


def test_unexpected_failure_is_generic_500_and_nothing_is_saved(
    client: TestClient, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed(engine, groups=2, per_group=5)

    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("password=hunter2 in SQL INSERT ...")

    monkeypatch.setattr(SASession, "commit", boom)  # fails while saving results
    response = process(client)
    monkeypatch.undo()

    assert response.status_code == 500
    assert "hunter2" not in response.text and "RuntimeError" not in response.text
    assert {(a.status, a.topic) for a in rows(engine).values()} == {("analyzed", None)}


def test_topic_labels_do_not_contain_english_stop_words(
    client: TestClient, engine: Engine
) -> None:
    """Regression: labels used to be built from words like 'the', 'and', 'to'."""
    seed(engine, groups=3, per_group=6)

    assert process(client).status_code == 200

    labels = {a.topic for a in rows(engine).values()} - {OUTLIER}
    assert labels
    for label in labels:
        words = {w for part in label.split(" · ") for w in part.split()}
        assert not words & ENGLISH_STOP_WORDS, label
