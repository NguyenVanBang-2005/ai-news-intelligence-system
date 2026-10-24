from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import DbSession, limit_search_rate, require_admin
from app.schemas.ask import (
    AiSearchRequest,
    AiSearchResponse,
    AskRequest,
    AskResponse,
    AskSource,
)
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
    dependencies=[Depends(require_admin)],
)
def ask(payload: AskRequest, db: DbSession) -> AskResponse:
    """Find stored articles for a search request or a link, with a summary of each."""

    # Imported here so missing ML libraries cannot prevent app.main from loading.
    try:
        from app.services.news_search import (
            LinkInputDisabledError,
            LinkUnreadableError,
            NewsSearchService,
        )
    except (ImportError, OSError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=AI_DEPENDENCIES_MISSING_MESSAGE,
        ) from exc

    try:
        result = NewsSearchService(db).ask(payload.input)
    except (LinkUnreadableError, LinkInputDisabledError) as exc:
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
        sources=[_ask_source(source) for source in result.sources],
    )


@router.post(
    "/search",
    response_model=AiSearchResponse,
    dependencies=[Depends(limit_search_rate)],
)
def search(payload: AiSearchRequest, db: DbSession) -> AiSearchResponse:
    """Public search in the stored articles. Never downloads links, calls the LLM or
    embeds articles; rate limited per IP and body size capped (see app.main)."""

    try:
        from app.services.news_search import LinkNotAllowedError, NewsSearchService
    except (ImportError, OSError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=AI_DEPENDENCIES_MISSING_MESSAGE,
        ) from exc

    try:
        sources = NewsSearchService(db).search(payload.input)
    except LinkNotAllowedError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except EmbeddingModelUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=MODEL_UNAVAILABLE_MESSAGE,
        ) from exc

    return AiSearchResponse(sources=[_ask_source(source) for source in sources])


def _ask_source(source) -> AskSource:
    return AskSource(
        id=source.article.id,
        title=source.article.title,
        url=source.article.url,
        source_name=source.article.source.name,
        published_at=source.article.published_at,
        similarity=round(source.similarity, 4),
        summary=source.summary,
        summary_method=source.summary_method,
    )
