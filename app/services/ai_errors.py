"""Errors of the AI pipeline. Kept free of ML imports so routes can use them at startup."""

from app.core.config import settings

AI_DEPENDENCIES_MISSING_MESSAGE = (
    "AI dependencies could not be loaded. Check the server's Python "
    "environment and Windows Application Control logs. "
    "RSS ingestion and baseline analysis remain available."
)
MODEL_UNAVAILABLE_MESSAGE = "The embedding model could not be loaded. Try again later."
PROCESSING_FAILED_MESSAGE = "AI processing failed."


class NotEnoughDocumentsError(ValueError):
    pass


class EmbeddingModelUnavailableError(RuntimeError):
    pass


def check_enough_documents(count: int) -> None:
    if count < settings.ai_min_documents:
        raise NotEnoughDocumentsError(
            "BERTopic requires at least "
            f"{settings.ai_min_documents} documents. "
            f"Current batch contains {count}."
        )
