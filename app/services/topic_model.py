from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from bertopic import BERTopic
from hdbscan import HDBSCAN
from sentence_transformers import SentenceTransformer
from sklearn.feature_extraction.text import CountVectorizer
from sqlalchemy.orm import Session
from umap import UMAP

from app.core.config import settings
from app.repositories.article import ArticleRepository


class NotEnoughDocumentsError(ValueError):
    pass


@dataclass(frozen=True)
class TopicProcessingResult:
    documents_received: int
    unique_documents: int
    semantic_duplicates: int
    topics_created: int
    articles_updated: int


@lru_cache(maxsize=1)
def get_embedding_model() -> SentenceTransformer:
    """
    Load the model only once.

    The first call may take longer because the model must be
    downloaded and loaded into memory.
    """

    return SentenceTransformer(
        settings.embedding_model_name
    )


class TopicModelService:
    def __init__(self, db: Session):
        self.repository = ArticleRepository(db)
        self.embedding_model = get_embedding_model()

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
            self._build_document(
                title=article.title,
                content=article.content,
            )
            for article in articles
        ]

        if len(documents) < settings.ai_min_documents:
            raise NotEnoughDocumentsError(
                "BERTopic requires at least "
                f"{settings.ai_min_documents} documents. "
                f"Current batch contains {len(documents)}."
            )

        embeddings = self.embedding_model.encode(
            documents,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )

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

        unique_documents = [
            documents[index]
            for index in unique_indices
        ]

        unique_embeddings = embeddings[unique_indices]

        topic_model = self._create_topic_model(
            document_count=len(unique_documents)
        )

        topics, probabilities = topic_model.fit_transform(
            unique_documents,
            unique_embeddings,
        )

        confidence_values = self._extract_confidences(
            probabilities,
            document_count=len(unique_documents),
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

            topic_number = int(topics[unique_position])

            topic_name = self._topic_name(
                topic_model,
                topic_number,
            )

            confidence = float(
                confidence_values[unique_position]
            )

            database_results.append(
                (
                    article.id,
                    topic_name,
                    round(confidence, 4),
                )
            )

        self.repository.save_ai_results(database_results)

        valid_topics = {
            int(topic)
            for topic in topics
            if int(topic) != -1
        }

        return TopicProcessingResult(
            documents_received=len(documents),
            unique_documents=len(unique_indices),
            semantic_duplicates=(
                len(documents) - len(unique_indices)
            ),
            topics_created=len(valid_topics),
            articles_updated=len(database_results),
        )

    @staticmethod
    def _build_document(
        *,
        title: str,
        content: str,
    ) -> str:
        content = content.strip()

        # Prevent one very long article from dominating processing.
        content = content[:10_000]

        return f"{title}. {content}".strip()

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

            for previous_index in unique_indices:
                similarity = float(
                    np.dot(
                        current_embedding,
                        embeddings[previous_index],
                    )
                )

                if similarity >= threshold:
                    canonical_index = previous_index
                    break

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

        min_cluster_size = max(
            2,
            min(10, document_count // 5),
        )

        umap_model = UMAP(
            n_neighbors=n_neighbors,
            n_components=n_components,
            min_dist=0.0,
            metric="cosine",
            random_state=42,
        )

        hdbscan_model = HDBSCAN(
            min_cluster_size=min_cluster_size,
            metric="euclidean",
            cluster_selection_method="eom",
            prediction_data=True,
        )

        vectorizer_model = CountVectorizer(
            ngram_range=(1, 2),
            min_df=1,
        )

        return BERTopic(
            umap_model=umap_model,
            hdbscan_model=hdbscan_model,
            vectorizer_model=vectorizer_model,
            calculate_probabilities=True,
            verbose=False,
        )

    @staticmethod
    def _extract_confidences(
        probabilities: object,
        *,
        document_count: int,
    ) -> np.ndarray:
        if probabilities is None:
            return np.full(document_count, 0.5)

        values = np.asarray(probabilities)

        if values.ndim == 1:
            return values

        if values.ndim == 2:
            return values.max(axis=1)

        return np.full(document_count, 0.5)

    @staticmethod
    def _topic_name(
        topic_model: BERTopic,
        topic_number: int,
    ) -> str:
        if topic_number == -1:
            return "Other / Outlier"

        words = topic_model.get_topic(topic_number)

        if not words:
            return f"Topic {topic_number}"

        keywords = [
            word.replace("_", " ").strip()
            for word, _ in words[:4]
        ]

        label = " · ".join(keywords)

        return label[:80]