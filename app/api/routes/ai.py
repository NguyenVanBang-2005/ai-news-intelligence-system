from fastapi import APIRouter, HTTPException, status

from app.api.deps import DbSession
from app.schemas.ai import (
    AIProcessRequest,
    AIProcessResponse,
)
from app.services.topic_model import (
    NotEnoughDocumentsError,
    TopicModelService,
)

router = APIRouter(
    prefix="/ai",
    tags=["ai"],
)


@router.post(
    "/process",
    response_model=AIProcessResponse,
)
def process_articles(
    payload: AIProcessRequest,
    db: DbSession,
) -> AIProcessResponse:
    try:
        result = TopicModelService(db).process(
            limit=payload.limit,
            duplicate_threshold=(
                payload.duplicate_threshold
            ),
            force=payload.force,
        )

    except NotEnoughDocumentsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "AI processing failed: "
                f"{type(exc).__name__}: {exc}"
            ),
        ) from exc

    return AIProcessResponse(
        documents_received=result.documents_received,
        unique_documents=result.unique_documents,
        semantic_duplicates=result.semantic_duplicates,
        topics_created=result.topics_created,
        articles_updated=result.articles_updated,
    )