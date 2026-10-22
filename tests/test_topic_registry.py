"""Stable topic labels across batches: centroid matching against stored topics."""

import numpy as np
import pytest
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.models.topic import Topic
from app.repositories.topic import TopicRepository
from app.services.topic_registry import NewTopic, TopicRegistry

AXIS_0 = np.array([1.0, 0.0, 0.0])
AXIS_1 = np.array([0.0, 1.0, 0.0])


def topic(
    label: str, embedding: np.ndarray, count: int, *, keyword: str = "word", article_id: int = 1
) -> NewTopic:
    return NewTopic(
        proposed_label=label,
        embeddings=np.tile(embedding, (count, 1)),
        keywords=[{"word": keyword, "weight": 0.5}],
        representative_article_ids=[article_id],
    )


def resolve(
    engine: Engine, new_topics: dict[int, NewTopic], min_similarity: float = 0.9
) -> dict[int, str]:
    with Session(engine) as db:
        registry = TopicRegistry(TopicRepository(db), min_similarity=min_similarity)
        labels = registry.resolve_labels(new_topics)
        db.commit()
    return labels


def stored_topics(engine: Engine) -> list[Topic]:
    with Session(engine) as db:
        return list(db.scalars(select(Topic).order_by(Topic.id)))


def test_first_batch_stores_every_topic_under_its_own_label(engine: Engine) -> None:
    labels = resolve(
        engine,
        {0: topic("senate · vote", AXIS_0, 4), 1: topic("match · goal", AXIS_1, 2)},
    )

    assert labels == {0: "senate · vote", 1: "match · goal"}
    assert [(t.label, t.article_count) for t in stored_topics(engine)] == [
        ("senate · vote", 4),
        ("match · goal", 2),
    ]


def test_later_batch_reuses_the_label_of_a_close_topic(engine: Engine) -> None:
    resolve(engine, {0: topic("senate · vote", AXIS_0, 4, keyword="old", article_id=1)})
    slightly_off = AXIS_0 + np.array([0.0, 0.1, 0.0])

    labels = resolve(
        engine,
        {
            7: topic("congress · election", slightly_off, 3, keyword="new", article_id=9),
            8: topic("match · goal", AXIS_1, 2),
        },
    )

    assert labels == {7: "senate · vote", 8: "match · goal"}
    topics = stored_topics(engine)
    assert [(t.label, t.article_count) for t in topics] == [
        ("senate · vote", 7),
        ("match · goal", 2),
    ]
    assert np.linalg.norm(topics[0].centroid) == pytest.approx(1.0)
    # The label is kept, the details are those of the latest batch.
    assert topics[0].keywords == [{"word": "new", "weight": 0.5}]
    assert topics[0].representative_article_ids == [9]


def test_topic_below_the_threshold_keeps_its_new_label(engine: Engine) -> None:
    resolve(engine, {0: topic("senate · vote", AXIS_0, 4)})

    labels = resolve(engine, {0: topic("match · goal", AXIS_1, 3)})

    assert labels == {0: "match · goal"}
    assert len(stored_topics(engine)) == 2


def test_centroid_of_another_embedding_size_is_ignored(engine: Engine) -> None:
    resolve(engine, {0: topic("senate · vote", np.array([1.0, 0.0]), 4)})

    labels = resolve(engine, {0: topic("congress · election", AXIS_0, 3)})

    assert labels == {0: "congress · election"}
