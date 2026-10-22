"""Article and query embeddings, shared by topic modelling and news search."""

import hashlib
from functools import lru_cache

import numpy as np
from sentence_transformers import SentenceTransformer

from app.core.config import settings
from app.models.article import Article
from app.repositories.article import ArticleRepository

# Prevent one very long article from dominating its embedding.
MAX_EMBEDDED_CONTENT_CHARS = 10_000


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


def build_document(*, title: str, content: str) -> str:
    content = content.strip()[:MAX_EMBEDDED_CONTENT_CHARS]

    return f"{title}. {content}".strip()


def embedding_key(document: str) -> str:
    """Identifies the model and text an embedding was computed for."""

    return hashlib.sha256(
        f"{settings.embedding_model_name}\n{document}".encode()
    ).hexdigest()


# intfloat/multilingual-e5-base was trained with instruction prefixes:
# "passage: " for texts to be found, "query: " for search requests.
# Embedding quality drops noticeably without them. The prefix is applied
# right before encoding, so the stored and displayed texts stay unprefixed.

def encode_passages(model: SentenceTransformer, texts: list[str]) -> np.ndarray:
    return _encode(model, [f"passage: {text}" for text in texts])


def encode_queries(model: SentenceTransformer, texts: list[str]) -> np.ndarray:
    return _encode(model, [f"query: {text}" for text in texts])


def _encode(model: SentenceTransformer, texts: list[str]) -> np.ndarray:
    return model.encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=False,
        convert_to_numpy=True,
    )


class ArticleEmbedder:
    """Embeds articles, encoding only those without a valid cached embedding."""

    def __init__(self, repository: ArticleRepository, model: SentenceTransformer):
        self.repository = repository
        self.model = model

    def embed(self, articles: list[Article]) -> np.ndarray:
        """One unit-length row per article, in the same order."""

        documents = [
            build_document(title=article.title, content=article.content)
            for article in articles
        ]
        keys = [embedding_key(document) for document in documents]

        embeddings = [
            article.cached_embedding(key)
            for article, key in zip(articles, keys, strict=True)
        ]

        missing = [
            index
            for index, embedding in enumerate(embeddings)
            if embedding is None
        ]

        if missing:
            fresh_embeddings = encode_passages(
                self.model,
                [documents[index] for index in missing],
            )

            for index, embedding in zip(missing, fresh_embeddings, strict=True):
                embeddings[index] = embedding.astype(np.float32)

            self.repository.save_embeddings(
                [
                    (articles[index], keys[index], embeddings[index])
                    for index in missing
                ]
            )

        return np.vstack(embeddings)
