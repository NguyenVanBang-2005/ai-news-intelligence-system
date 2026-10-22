"""The /api/v1/ai endpoints: contract, persistence and failure behaviour.

MOCK NOTICE: the sentence-transformer is replaced by `FakeEmbedder` (deterministic vectors,
one direction per synthetic topic), so these tests never download a model. UMAP, HDBSCAN,
BERTopic, the repository and the database are real. They verify validity, ID mapping,
storage and error handling. Real-model behaviour is covered by the Docker acceptance run
(tests/e2e/, docs/e2e-acceptance.md). Exact labels / topic counts are deliberately not asserted.

Processing runs as a background job; FastAPI's TestClient finishes background tasks before it
returns the response, so a job is already done when it is first polled.
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

try:
    import app.services.topic_model as topic_model
except (ImportError, OSError) as exc:  # optional ML stack missing or blocked by the OS
    pytest.skip(f"AI dependencies unavailable: {exc}", allow_module_level=True)

from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS

from app.models.ai_job import AIJob
from app.models.article import Article
from app.models.source import Source
from app.models.topic import Topic
from app.repositories.article import ArticleRepository

OUTLIER = "Other / Outlier"
START = datetime(2026, 9, 1, tzinfo=UTC)


class FakeEmbedder:
    """Maps 'G<k>' in the text to axis k plus small deterministic noise, L2-normalised.

    Texts without a group marker (single words that KeyBERTInspired embeds) get noise only."""

    def encode(self, documents: list[str], **kwargs: object) -> np.ndarray:
        vectors = []
        for doc in documents:
            vec = np.zeros(16)
            if group := re.search(r"G(\d+)", doc):
                vec[int(group.group(1))] = 1.0
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
    """Start a job: the raw POST response."""
    return client.post("/api/v1/ai/process", json=body)


def run_job(client: TestClient, **body: object) -> dict:
    """Start a job and return its finished state."""
    response = process(client, **body)
    assert response.status_code == 202, response.text
    job = client.get(f"/api/v1/ai/process/{response.json()['id']}").json()
    assert job["status"] in ("succeeded", "failed"), job
    return job


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


def test_job_goes_from_pending_to_succeeded(client: TestClient, engine: Engine) -> None:
    seed(engine, groups=2, per_group=5)

    started = process(client)

    assert started.status_code == 202
    assert started.json()["status"] == "pending"
    assert started.json()["result"] is None
    job = client.get(f"/api/v1/ai/process/{started.json()['id']}").json()
    assert job["status"] == "succeeded"
    assert job["error"] is None
    assert job["started_at"] and job["finished_at"]


def test_unknown_job_is_404(client: TestClient) -> None:
    assert client.get("/api/v1/ai/process/does-not-exist").status_code == 404


def test_a_second_job_is_refused_while_one_is_active(
    client: TestClient, engine: Engine
) -> None:
    seed(engine, groups=2, per_group=5)
    with Session(engine) as db:
        db.add(AIJob(id="active-job", status="running", parameters={}))
        db.commit()

    response = process(client)

    assert response.status_code == 409
    assert "active-job" in response.json()["detail"]


def test_a_dead_job_does_not_block_new_ones(client: TestClient, engine: Engine) -> None:
    seed(engine, groups=2, per_group=5)
    with Session(engine) as db:
        db.add(AIJob(id="dead-job", status="running", parameters={},
                     created_at=datetime.now(UTC) - timedelta(days=1)))
        db.commit()

    assert run_job(client)["status"] == "succeeded"


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

    job = run_job(client)

    assert job["status"] == "succeeded"
    body = job["result"]
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


def test_result_says_where_confidence_came_from_and_how_coherent_the_topics_are(
    client: TestClient, engine: Engine
) -> None:
    seed(engine, groups=3, per_group=6)

    result = run_job(client)["result"]

    assert result["confidence_method"] == "hdbscan_soft"
    assert result["topic_coherence"] is None or -1.0 <= result["topic_coherence"] <= 1.0


def test_flat_confidence_is_reported_as_fallback() -> None:
    extract = topic_model.TopicModelService._extract_confidences

    values, method = extract(None, document_count=3)
    assert method == "fallback" and list(values) == [0.5, 0.5, 0.5]

    values, method = extract(np.zeros((2, 2, 2)), document_count=2)
    assert method == "fallback"

    values, method = extract(np.array([[0.2, 0.7], [0.9, 0.1]]), document_count=2)
    assert method == "hdbscan_soft" and list(values) == [0.7, 0.9]


def test_semantic_duplicates_share_the_canonical_articles_result(
    client: TestClient, engine: Engine
) -> None:
    ids = seed(engine, groups=3, per_group=5, duplicates_of=(0, 7))

    body = run_job(client)["result"]

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
    assert run_job(client)["status"] == "succeeded"
    with Session(engine) as db:  # sentinel shows exactly which rows a later run rewrites
        for article in db.scalars(select(Article)):
            article.topic, article.confidence = "SENTINEL", -1.0
        db.commit()

    again = process(client)
    assert again.status_code == 409  # nothing eligible without force
    assert {a.topic for a in rows(engine).values()} == {"SENTINEL"}

    forced = run_job(client, force=True, limit=10)
    assert forced["status"] == "succeeded"
    assert forced["result"]["articles_updated"] == 10
    rewritten = {i for i, a in rows(engine).items() if a.topic != "SENTINEL"}
    assert rewritten == set(ids["usable"][:10])  # the 10 oldest by created_at


def test_identical_documents_fail_the_job_and_are_not_marked_analysed(
    client: TestClient, engine: Engine
) -> None:
    seed(engine, groups=0, identical=12)

    job = run_job(client)

    assert job["status"] == "failed"
    assert "Unique documents: 1" in job["error"]
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

    job = run_job(client)

    assert job["status"] == "succeeded"
    assert job["result"]["topics_created"] == 0
    assert job["result"]["topic_coherence"] is None
    for article in rows(engine).values():
        assert (article.topic, article.confidence, article.status) == (OUTLIER, 0.0, "ai_analyzed")


def test_model_failure_fails_the_job_without_leaking_details_and_crud_still_works(
    client: TestClient, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken() -> None:
        raise OSError("401 for https://huggingface.co/secret-org/model token=hf_SECRET")

    monkeypatch.setattr(topic_model, "get_embedding_model", broken)
    seed(engine, groups=2, per_group=5)

    job = run_job(client)

    assert job["status"] == "failed"
    assert "model could not be loaded" in job["error"]
    assert "hf_SECRET" not in str(job) and "huggingface" not in str(job)
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


def test_unexpected_failure_fails_the_job_with_a_generic_error_and_saves_nothing(
    client: TestClient, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed(engine, groups=2, per_group=5)

    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("password=hunter2 in SQL INSERT ...")

    monkeypatch.setattr(ArticleRepository, "save_ai_results", boom)

    job = run_job(client)

    assert job["status"] == "failed"
    assert job["error"] == "AI processing failed."
    assert "hunter2" not in str(job) and "RuntimeError" not in str(job)
    assert {(a.status, a.topic) for a in rows(engine).values()} == {("analyzed", None)}
    with Session(engine) as db:  # the topics of the failed run were rolled back
        assert db.scalars(select(Topic)).all() == []


def test_topic_labels_do_not_contain_english_stop_words(
    client: TestClient, engine: Engine
) -> None:
    """Regression: labels used to be built from words like 'the', 'and', 'to'."""
    seed(engine, groups=3, per_group=6)

    assert run_job(client)["status"] == "succeeded"

    labels = {a.topic for a in rows(engine).values()} - {OUTLIER}
    assert labels
    for label in labels:
        words = {w for part in label.split(" · ") for w in part.split()}
        assert not words & ENGLISH_STOP_WORDS, label


def test_topics_endpoint_shows_size_keywords_and_representative_articles(
    client: TestClient, engine: Engine
) -> None:
    assert client.get("/api/v1/ai/topics").json() == []
    ids = seed(engine, groups=3, per_group=6)
    run_job(client)

    topics = client.get("/api/v1/ai/topics").json()

    assert topics
    assert sum(t["size"] for t in topics) <= 18
    assert [t["size"] for t in topics] == sorted((t["size"] for t in topics), reverse=True)
    for topic in topics:
        assert topic["keywords"] and {"word", "weight"} == set(topic["keywords"][0])
        assert 1 <= len(topic["representative_articles"]) <= 3
        for article in topic["representative_articles"]:
            assert article["id"] in ids["usable"]
            assert article["url"].startswith("https://seed.example/")
        stored_topic = {a["topic"] for a in client.get(
            "/api/v1/articles", params={"topic": topic["label"], "limit": 100}).json()["items"]}
        assert stored_topic == {topic["label"]}


def test_label_of_a_stored_topic_is_reused_in_a_later_batch(
    client: TestClient, engine: Engine
) -> None:
    seed(engine, groups=3, per_group=6)
    assert run_job(client)["status"] == "succeeded"
    with Session(engine) as db:
        first_labels = {a.topic for a in db.scalars(select(Article))}
        for topic in db.scalars(select(Topic)):  # a label chosen "on an earlier day"
            topic.label = f"STORED {topic.id}"
        db.commit()

    assert run_job(client, force=True)["status"] == "succeeded"

    labels = {a.topic for a in rows(engine).values()}
    assert labels and all(label.startswith("STORED ") for label in labels - {OUTLIER})
    assert first_labels != labels


def test_embeddings_are_cached_and_recomputed_only_when_the_text_changes(
    client: TestClient, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    cached_for: list[int] = []  # articles that had to be embedded, one entry per article
    original = Article.cache_embedding

    def spy(self: Article, key: str, vector: np.ndarray) -> None:
        cached_for.append(self.id)
        original(self, key, vector)

    monkeypatch.setattr(Article, "cache_embedding", spy)
    ids = seed(engine, groups=3, per_group=6)

    assert run_job(client)["status"] == "succeeded"
    assert sorted(cached_for) == sorted(ids["usable"])
    assert all(a.embedding is not None for a in rows(engine).values())

    cached_for.clear()
    assert run_job(client, force=True)["status"] == "succeeded"
    assert cached_for == []  # everything came from the cache

    with Session(engine) as db:
        db.get(Article, ids["usable"][0]).content = "G0 a rewritten story"
        db.commit()
    assert run_job(client, force=True)["status"] == "succeeded"
    assert cached_for == [ids["usable"][0]]  # only the changed article


class StubTopicModel:
    """Records what the service asks BERTopic to do with outliers and close topics."""

    vectorizer_model = "vectorizer"
    representation_model = "representation"

    def __init__(self, reduced_topics: list[int]):
        self.reduced_topics = reduced_topics
        self.topics_ = reduced_topics
        self.calls: list[str] = []

    def reduce_outliers(self, documents, topics, **kwargs):
        self.calls.append(f"reduce_outliers:{kwargs['strategy']}:{kwargs['threshold']}")
        return self.reduced_topics

    def update_topics(self, documents, **kwargs):
        assert kwargs["topics"] == self.reduced_topics
        assert kwargs["vectorizer_model"] and kwargs["representation_model"]
        self.calls.append("update_topics")

    def reduce_topics(self, documents, nr_topics):
        self.calls.append(f"reduce_topics:{nr_topics}")


def test_outliers_are_moved_to_their_closest_topic() -> None:
    stub = StubTopicModel(reduced_topics=[0, 0, 1, 1])
    documents, embeddings = ["a", "b", "c", "d"], np.zeros((4, 2))

    result = topic_model.TopicModelService._reduce_outliers(
        stub, documents, embeddings, [0, -1, 1, -1]
    )

    assert result == [0, 0, 1, 1]
    threshold = topic_model.settings.ai_outlier_min_similarity
    assert stub.calls == [f"reduce_outliers:embeddings:{threshold}", "update_topics"]


@pytest.mark.parametrize("topics", [[0, 0, 1, 1], [-1, -1, -1, -1]])
def test_outliers_are_left_alone_when_there_is_nothing_to_move_them_to(
    topics: list[int],
) -> None:
    stub = StubTopicModel(reduced_topics=[])

    result = topic_model.TopicModelService._reduce_outliers(
        stub, ["a"] * 4, np.zeros((4, 2)), topics
    )

    assert result == topics and stub.calls == []


def test_close_topics_are_merged_only_when_there_are_several() -> None:
    merge = topic_model.TopicModelService._merge_close_topics

    few = StubTopicModel(reduced_topics=[0, 1, -1])
    assert merge(few, ["a"] * 3, [0, 1, -1]) == [0, 1, -1] and few.calls == []

    many = StubTopicModel(reduced_topics=[0, 0, 1, -1])
    assert merge(many, ["a"] * 4, [0, 1, 2, -1]) == [0, 0, 1, -1]
    assert many.calls == ["reduce_topics:auto"]


def test_zero_shot_category_names_the_matching_articles(
    client: TestClient, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Group 0 is close to the 'G0 Politics' category, so its articles are named after it."""
    monkeypatch.setattr(topic_model.settings, "ai_zeroshot_topics", ["G0 Politics"])
    ids = seed(engine, groups=3, per_group=6)

    assert run_job(client)["status"] == "succeeded"

    stored = rows(engine)
    assert {stored[i].topic for i in ids["usable"][:6]} == {"G0 Politics"}
    assert "G0 Politics" not in {stored[i].topic for i in ids["usable"][6:]}
