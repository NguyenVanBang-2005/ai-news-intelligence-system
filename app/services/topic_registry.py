from dataclasses import dataclass

import numpy as np

from app.repositories.topic import TopicRepository


@dataclass(frozen=True)
class NewTopic:
    """A topic found in the current batch."""

    proposed_label: str
    embeddings: np.ndarray
    keywords: list[dict]
    representative_article_ids: list[int]


def _unit(vector: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(vector)
    return vector / norm if norm else vector


class TopicRegistry:
    """Keeps topic labels stable across batches.

    Every batch is clustered from scratch, so BERTopic invents new labels each time. Here each
    new topic's centroid is compared with the centroids of topics seen before: a close enough
    match takes over the stored label (and updates the stored centroid), anything else is
    stored as a new topic under its freshly generated label. Keywords and representative
    articles always come from the latest batch.
    """

    def __init__(self, repository: TopicRepository, *, min_similarity: float):
        self.repository = repository
        self.min_similarity = min_similarity

    def resolve_labels(self, new_topics: dict[int, NewTopic]) -> dict[int, str]:
        """Return the final label for each topic number in `new_topics`."""
        # Topics created in this call are not candidates: BERTopic already
        # decided that the topics of one batch are different from each other.
        known_topics = self.repository.list_all()
        labels: dict[int, str] = {}

        for topic_number, new_topic in new_topics.items():
            article_count = len(new_topic.embeddings)
            centroid = _unit(new_topic.embeddings.mean(axis=0))

            match = self._closest_topic(known_topics, centroid)

            if match is None:
                self.repository.add(
                    label=new_topic.proposed_label,
                    centroid=centroid.tolist(),
                    article_count=article_count,
                    keywords=new_topic.keywords,
                    representative_article_ids=new_topic.representative_article_ids,
                )
                labels[topic_number] = new_topic.proposed_label
                continue

            merged_centroid = _unit(
                np.asarray(match.centroid) * match.article_count + centroid * article_count
            )
            self.repository.update(
                match,
                centroid=merged_centroid.tolist(),
                article_count=match.article_count + article_count,
                keywords=new_topic.keywords,
                representative_article_ids=new_topic.representative_article_ids,
            )
            labels[topic_number] = match.label

        return labels

    def _closest_topic(self, known_topics: list, centroid: np.ndarray):
        # A stored centroid of another size comes from a different embedding model.
        comparable = [topic for topic in known_topics if len(topic.centroid) == len(centroid)]

        if not comparable:
            return None

        similarities = np.asarray([topic.centroid for topic in comparable]) @ centroid
        best = int(similarities.argmax())

        if similarities[best] < self.min_similarity:
            return None

        return comparable[best]
