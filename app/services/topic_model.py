import logging
from dataclasses import dataclass, replace

import numpy as np
from bertopic import BERTopic
from bertopic.backend import BaseEmbedder
from bertopic.representation import (
    KeyBERTInspired,
    MaximalMarginalRelevance,
)
from hdbscan import HDBSCAN
from sentence_transformers import SentenceTransformer
from sklearn.feature_extraction.text import CountVectorizer
from sqlalchemy.orm import Session
from umap import UMAP

from app.core.config import settings
from app.repositories.article import ArticleRepository
from app.repositories.topic import TopicRepository
from app.services.ai_errors import (
    EmbeddingModelUnavailableError,
    NotEnoughDocumentsError,
    check_enough_documents,
)
from app.services.embeddings import (
    ArticleEmbedder,
    build_document,
    encode_passages,
    get_embedding_model,
)
from app.services.topic_coherence import npmi_coherence
from app.services.topic_registry import NewTopic, TopicRegistry

logger = logging.getLogger(__name__)

OUTLIER_TOPIC = -1
OUTLIER_LABEL = "Other / Outlier"

# Merging topics automatically only makes sense when there are several to merge.
MIN_TOPICS_TO_MERGE = 3

# BERTopic's default (10) gives KeyBERTInspired/MMR a narrow pool to re-rank and
# diversify from. 20 candidates leaves room for MMR to drop redundant words
# while the final label (the first few words) stays meaningful.
TOP_N_WORDS = 20

# How much of each topic the API shows: keywords with weights, and the articles
# closest to the topic's centre.
KEYWORD_COUNT = 10
REPRESENTATIVE_COUNT = 3

# Where the per-article confidence came from (see _extract_confidences).
CONFIDENCE_HDBSCAN_SOFT = "hdbscan_soft"
CONFIDENCE_FALLBACK = "fallback"
FALLBACK_CONFIDENCE = 0.5

# HDBSCAN sizes, tuned on a 200-article real corpus (docs/evidence/topic_robustness.txt,
# DATA-3b). The old cap of 10 with default min_samples gave 2 topics, one holding 76%.
MAX_MIN_CLUSTER_SIZE = 8
HDBSCAN_MIN_SAMPLES = 1


def hdbscan_sizes(document_count: int) -> tuple[int, int]:
    """(min_cluster_size, min_samples) for a batch of `document_count` documents."""

    min_cluster_size = max(2, min(MAX_MIN_CLUSTER_SIZE, document_count // 5))

    return min_cluster_size, HDBSCAN_MIN_SAMPLES


@dataclass(frozen=True)
class TopicProcessingResult:
    documents_received: int
    unique_documents: int
    semantic_duplicates: int
    topics_created: int
    articles_updated: int
    confidence_method: str
    topic_coherence: float | None


@dataclass(frozen=True)
class Clustering:
    topics: list[int]
    confidences: np.ndarray
    confidence_method: str
    topic_model: BERTopic


class PassageEmbedder(BaseEmbedder):
    """
    Lets BERTopic embed candidate words (KeyBERTInspired) with the same
    prefixed encoding used for the articles.
    """

    def __init__(self, model: SentenceTransformer):
        super().__init__()
        self.model = model

    def embed(
        self,
        documents: list[str],
        verbose: bool = False,
    ) -> np.ndarray:
        return encode_passages(self.model, documents)


class TopicModelService:
    def __init__(self, db: Session):
        self.repository = ArticleRepository(db)
        self.topic_registry = TopicRegistry(
            TopicRepository(db),
            min_similarity=settings.ai_topic_match_threshold,
        )

    def process(
        self,
        *,
        limit: int,
        duplicate_threshold: float,
        force: bool,
    ) -> TopicProcessingResult:
        articles = self.repository.list_for_ai_processing(
            limit=limit,
            force=force,
        )

        documents = [
            build_document(
                title=article.title,
                content=article.content,
            )
            for article in articles
        ]

        check_enough_documents(len(documents))

        # Loaded only after the size check, so a batch that is too small
        # never pays for (or fails on) the model download.
        try:
            embedding_model = get_embedding_model()
        except OSError as exc:
            raise EmbeddingModelUnavailableError from exc

        embeddings = ArticleEmbedder(
            self.repository,
            embedding_model,
        ).embed(articles)

        (
            unique_indices,
            canonical_index_for_document,
        ) = self._find_unique_documents(
            embeddings,
            threshold=duplicate_threshold,
        )

        if len(unique_indices) < settings.ai_min_documents:
            raise NotEnoughDocumentsError(
                "There are not enough unique documents after "
                "semantic duplicate detection. "
                f"Unique documents: {len(unique_indices)}."
            )

        unique_articles = [
            articles[index]
            for index in unique_indices
        ]

        unique_documents = [
            documents[index]
            for index in unique_indices
        ]

        unique_embeddings = embeddings[unique_indices]

        clustering = self._cluster(
            unique_documents,
            unique_embeddings,
        )

        topic_names = self._name_topics(
            clustering.topic_model,
            clustering.topics,
            unique_embeddings,
            [article.id for article in unique_articles],
        )

        topic_coherence = self._topic_coherence(
            clustering,
            unique_documents,
        )

        unique_position_by_original_index = {
            original_index: unique_position
            for unique_position, original_index
            in enumerate(unique_indices)
        }

        database_results: list[tuple[int, str, float]] = []

        for document_index, article in enumerate(articles):
            canonical_original_index = (
                canonical_index_for_document[document_index]
            )

            unique_position = (
                unique_position_by_original_index[
                    canonical_original_index
                ]
            )

            topic_name = topic_names[clustering.topics[unique_position]]

            confidence = float(
                clustering.confidences[unique_position]
            )

            database_results.append(
                (
                    article.id,
                    topic_name,
                    round(confidence, 4),
                )
            )

        # Also commits the topic centroids stored by _name_topics.
        self.repository.save_ai_results(database_results)

        valid_topics = set(clustering.topics) - {OUTLIER_TOPIC}

        return TopicProcessingResult(
            documents_received=len(documents),
            unique_documents=len(unique_indices),
            semantic_duplicates=(
                len(documents) - len(unique_indices)
            ),
            topics_created=len(valid_topics),
            articles_updated=len(database_results),
            confidence_method=clustering.confidence_method,
            topic_coherence=topic_coherence,
        )

    def _cluster(
        self,
        documents: list[str],
        embeddings: np.ndarray,
    ) -> Clustering:
        """Fit BERTopic, then clean up the clustering of a small batch."""

        topic_model = self._create_topic_model(
            document_count=len(documents)
        )

        topics, probabilities = topic_model.fit_transform(
            documents,
            embeddings,
        )

        (
            confidences,
            confidence_method,
        ) = self._extract_confidences(
            probabilities,
            document_count=len(documents),
        )

        topics = self._reduce_outliers(
            topic_model,
            documents,
            embeddings,
            [int(topic) for topic in topics],
        )

        topics = self._merge_close_topics(
            topic_model,
            documents,
            topics,
        )

        return Clustering(
            topics=[int(topic) for topic in topics],
            confidences=confidences,
            confidence_method=confidence_method,
            topic_model=topic_model,
        )

    @staticmethod
    def _topic_coherence(
        clustering: Clustering,
        documents: list[str],
    ) -> float | None:
        topic_words = [
            [
                word
                for word, _ in clustering.topic_model.get_topic(topic)[:KEYWORD_COUNT]
            ]
            for topic in sorted(set(clustering.topics) - {OUTLIER_TOPIC})
        ]

        coherence = npmi_coherence(topic_words, documents)

        logger.info("Topic coherence (NPMI) of the batch: %s", coherence)

        return coherence

    @staticmethod
    def _reduce_outliers(
        topic_model: BERTopic,
        documents: list[str],
        embeddings: np.ndarray,
        topics: list[int],
    ) -> list[int]:
        """
        HDBSCAN dumps many documents of a small batch into the -1 bucket.
        Move each one to its closest topic when it is similar enough.
        """

        has_outliers = OUTLIER_TOPIC in topics
        has_topics = any(
            topic != OUTLIER_TOPIC
            for topic in topics
        )

        if not (has_outliers and has_topics):
            return topics

        new_topics = topic_model.reduce_outliers(
            documents,
            topics,
            strategy="embeddings",
            embeddings=embeddings,
            threshold=settings.ai_outlier_min_similarity,
        )

        # Documents moved between topics, so topic words and sizes must be
        # recomputed. update_topics() drops the vectorizer and representation
        # model unless they are passed in again.
        topic_model.update_topics(
            documents,
            topics=new_topics,
            top_n_words=TOP_N_WORDS,
            vectorizer_model=topic_model.vectorizer_model,
            representation_model=topic_model.representation_model,
        )

        return list(new_topics)

    @staticmethod
    def _merge_close_topics(
        topic_model: BERTopic,
        documents: list[str],
        topics: list[int],
    ) -> list[int]:
        """Small daily batches often split one story over several clusters."""

        topic_count = len(set(topics) - {OUTLIER_TOPIC})

        if topic_count < MIN_TOPICS_TO_MERGE:
            return topics

        topic_model.reduce_topics(documents, nr_topics="auto")

        return list(topic_model.topics_)

    def _name_topics(
        self,
        topic_model: BERTopic,
        topics: list[int],
        embeddings: np.ndarray,
        article_ids: list[int],
    ) -> dict[int, str]:
        """
        Map each topic number to its final label.

        The label BERTopic generated for this batch is replaced by the label
        of an earlier, matching topic when there is one.
        """

        topic_array = np.asarray(topics)
        article_id_array = np.asarray(article_ids)

        new_topics: dict[int, NewTopic] = {}

        for topic in sorted(set(topics) - {OUTLIER_TOPIC}):
            in_topic = topic_array == topic

            new_topics[topic] = NewTopic(
                proposed_label=self._topic_label(topic_model, topic),
                embeddings=embeddings[in_topic],
                keywords=[
                    {"word": word, "weight": round(float(weight), 4)}
                    for word, weight in topic_model.get_topic(topic)[:KEYWORD_COUNT]
                ],
                representative_article_ids=self._representative_article_ids(
                    embeddings[in_topic],
                    article_id_array[in_topic],
                ),
            )

        category_labels = self._category_labels(
            {topic: new_topic.embeddings for topic, new_topic in new_topics.items()}
        )

        for topic, label in category_labels.items():
            new_topics[topic] = replace(new_topics[topic], proposed_label=label)

        names = self.topic_registry.resolve_labels(new_topics)
        names[OUTLIER_TOPIC] = OUTLIER_LABEL

        return names

    @staticmethod
    def _representative_article_ids(
        embeddings: np.ndarray,
        article_ids: np.ndarray,
    ) -> list[int]:
        """The articles closest to the centre of the topic, best first."""

        centroid = embeddings.mean(axis=0)
        similarities = embeddings @ centroid
        closest = np.argsort(-similarities)[:REPRESENTATIVE_COUNT]

        return [int(article_ids[index]) for index in closest]

    @staticmethod
    def _find_unique_documents(
        embeddings: np.ndarray,
        *,
        threshold: float,
    ) -> tuple[list[int], list[int]]:
        """
        Because embeddings are normalized, the dot product is
        equivalent to cosine similarity.

        canonical_index_for_document[i] tells which unique article
        represents document i.
        """

        unique_indices: list[int] = []
        canonical_index_for_document: list[int] = []

        for current_index, current_embedding in enumerate(
            embeddings
        ):
            canonical_index = current_index

            if unique_indices:
                similarities = (
                    embeddings[unique_indices] @ current_embedding
                )
                similar = np.flatnonzero(similarities >= threshold)

                if similar.size:
                    canonical_index = unique_indices[int(similar[0])]

            if canonical_index == current_index:
                unique_indices.append(current_index)

            canonical_index_for_document.append(
                canonical_index
            )

        return (
            unique_indices,
            canonical_index_for_document,
        )

    @staticmethod
    def _create_topic_model(
        document_count: int,
    ) -> BERTopic:
        n_neighbors = min(
            15,
            max(2, document_count - 1),
        )

        n_components = min(
            5,
            max(2, document_count - 2),
        )

        min_cluster_size, min_samples = hdbscan_sizes(document_count)

        umap_model = UMAP(
            n_neighbors=n_neighbors,
            n_components=n_components,
            min_dist=0.0,
            metric="cosine",
            random_state=42,
        )

        hdbscan_model = HDBSCAN(
            min_cluster_size=min_cluster_size,
            min_samples=min_samples,
            metric="euclidean",
            cluster_selection_method="eom",
            prediction_data=True,
        )

        vectorizer_model = CountVectorizer(
            # Without this, labels are built from words like "the" and "and".
            # English only: other languages' stop words still reach the labels.
            stop_words="english",
            ngram_range=(1, 2),
            min_df=1,
        )

        # Topic labels go through two passes:
        #   1. KeyBERTInspired re-scores the raw c-TF-IDF candidate words by
        #      their embedding similarity to the topic's own documents, so
        #      words that are merely frequent (but off-topic) rank lower
        #      than words that actually capture what the cluster is about.
        #   2. MaximalMarginalRelevance then trims that re-scored list down,
        #      dropping near-synonyms ("election" / "elections") so the
        #      final label is a diverse, non-redundant set of keywords
        #      instead of four variations on the same word.
        # Running them as a list applies them in order: each step refines
        # the output of the previous one.
        representation_model = [
            KeyBERTInspired(top_n_words=TOP_N_WORDS),
            MaximalMarginalRelevance(
                diversity=0.3,
                top_n_words=TOP_N_WORDS,
            ),
        ]

        return BERTopic(
            # Documents are passed to fit_transform() already embedded. The
            # model is still needed to embed candidate words (KeyBERTInspired)
            # with the same multilingual model.
            embedding_model=PassageEmbedder(get_embedding_model()),
            umap_model=umap_model,
            hdbscan_model=hdbscan_model,
            vectorizer_model=vectorizer_model,
            representation_model=representation_model,
            top_n_words=TOP_N_WORDS,
            calculate_probabilities=True,
            verbose=False,
        )

    @staticmethod
    def _extract_confidences(
        probabilities: object,
        *,
        document_count: int,
    ) -> tuple[np.ndarray, str]:
        """
        Returns one confidence per document and where it came from:
        "hdbscan_soft" when HDBSCAN's soft-clustering probabilities were
        usable, "fallback" when a flat default had to be used instead.
        """

        if probabilities is not None:
            values = np.asarray(probabilities)

            if values.ndim == 1:
                return values, CONFIDENCE_HDBSCAN_SOFT

            if values.ndim == 2:
                return values.max(axis=1), CONFIDENCE_HDBSCAN_SOFT

        return (
            np.full(document_count, FALLBACK_CONFIDENCE),
            CONFIDENCE_FALLBACK,
        )

    @staticmethod
    def _category_labels(
        embeddings_by_topic: dict[int, np.ndarray],
    ) -> dict[int, str]:
        """
        Name a topic after the editorial category (AI_ZEROSHOT_TOPICS) its
        articles are closest to, if they are similar enough. Other topics
        keep the keywords BERTopic found, so new subjects are still discovered.

        BERTopic's own zero-shot mode is avoided on purpose: it breaks when
        outliers or topics are reduced afterwards.
        """

        categories = settings.ai_zeroshot_topics

        if not categories or not embeddings_by_topic:
            return {}

        category_embeddings = encode_passages(
            get_embedding_model(),
            categories,
        )

        labels: dict[int, str] = {}

        for topic, embeddings in embeddings_by_topic.items():
            centroid = embeddings.mean(axis=0)
            centroid = centroid / np.linalg.norm(centroid)

            similarities = category_embeddings @ centroid
            best = int(similarities.argmax())

            if similarities[best] >= settings.ai_zeroshot_min_similarity:
                labels[topic] = categories[best][:80]

        return labels

    @staticmethod
    def _topic_label(
        topic_model: BERTopic,
        topic_number: int,
    ) -> str:
        words = topic_model.get_topic(topic_number)

        if not words:
            return f"Topic {topic_number}"

        keywords = [
            word.replace("_", " ").strip()
            for word, _ in words[:4]
        ]

        label = " · ".join(keywords)

        return label[:80]
