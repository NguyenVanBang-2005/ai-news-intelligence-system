"""HDBSCAN size formula of the topic model (pure function, no embedding model needed)."""

import pytest

try:
    from app.services.topic_model import TopicModelService, hdbscan_sizes
except (ImportError, OSError) as exc:  # optional ML stack missing or blocked by the OS
    pytest.skip(f"AI dependencies unavailable: {exc}", allow_module_level=True)


@pytest.mark.parametrize(
    ("document_count", "expected"),
    [(10, (2, 1)), (30, (6, 1)), (50, (8, 1)), (200, (8, 1))],
)
def test_hdbscan_sizes(document_count: int, expected: tuple[int, int]) -> None:
    assert hdbscan_sizes(document_count) == expected


def test_min_cluster_size_never_below_two() -> None:
    assert hdbscan_sizes(2) == (2, 1)


def test_topic_model_uses_the_sizes(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.topic_model as topic_model

    # Building BERTopic must not load the real embedding model.
    monkeypatch.setattr(topic_model, "get_embedding_model", lambda: object())
    hdbscan = TopicModelService._create_topic_model(document_count=200).hdbscan_model
    assert (hdbscan.min_cluster_size, hdbscan.min_samples) == (8, 1)
