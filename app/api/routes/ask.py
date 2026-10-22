from fastapi import APIRouter, HTTPException, status

from app.api.deps import DbSession
from app.schemas.ask import AskRequest, AskResponse, AskSource
from app.services.ai_errors import (
    AI_DEPENDENCIES_MISSING_MESSAGE,
    MODEL_UNAVAILABLE_MESSAGE,
    EmbeddingModelUnavailableError,
)

router = APIRouter(
    prefix="/ai",
    tags=["ask"],
)


@router.post(
    "/ask",
    response_model=AskResponse,
)
def ask(payload: AskRequest, db: DbSession) -> AskResponse:
    """Find stored articles for a search request or a link, with a summary of each."""

    # Imported here so missing ML libraries cannot prevent app.main from loading.
    try:
        from app.services.news_search import LinkUnreadableError, NewsSearchService
    except (ImportError, OSError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=AI_DEPENDENCIES_MISSING_MESSAGE,
        ) from exc

    try:
        result = NewsSearchService(db).ask(payload.input)
    except LinkUnreadableError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except EmbeddingModelUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=MODEL_UNAVAILABLE_MESSAGE,
        ) from exc

    return AskResponse(
        answer=result.answer,
        sources=[
            AskSource(
                id=source.article.id,
                title=source.article.title,
                url=source.article.url,
                source_name=source.article.source.name,
                published_at=source.article.published_at,
                similarity=round(source.similarity, 4),
                summary=source.summary,
                summary_method=source.summary_method,
            )
            for source in result.sources
        ],
    )
