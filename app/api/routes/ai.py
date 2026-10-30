from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from app.api.deps import DbSession, SessionFactory, require_admin
from app.core.config import settings
from app.repositories.ai_job import AIJobAlreadyActiveError, AIJobRepository
from app.repositories.article import ArticleRepository
from app.repositories.topic import TopicRepository
from app.schemas.ai import (
    AIJobRead,
    AIProcessRequest,
    RepresentativeArticle,
    TopicRead,
)
from app.services.ai_errors import (
    AI_DEPENDENCIES_MISSING_MESSAGE,
    NotEnoughDocumentsError,
    check_enough_documents,
)
from app.services.ai_jobs import run_ai_job

router = APIRouter(
    prefix="/ai",
    tags=["ai"],
)


@router.post(
    "/process",
    response_model=AIJobRead,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_admin)],
)
def process_articles(
    payload: AIProcessRequest,
    db: DbSession,
    session_factory: SessionFactory,
    background_tasks: BackgroundTasks,
) -> AIJobRead:
    """Start processing in the background. Poll GET /ai/process/{job_id} for the outcome."""

    # Native ML dependencies are optional for starting the baseline API.
    # Import here so a missing/blocked DLL cannot prevent app.main from loading.
    try:
        import app.services.topic_model  # noqa: F401
    except (ImportError, OSError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=AI_DEPENDENCIES_MISSING_MESSAGE,
        ) from exc

    # Cheap checks first, so the caller learns right away about problems that
    # a job could not fix.
    try:
        check_enough_documents(
            ArticleRepository(db).count_for_ai_processing(
                limit=payload.limit,
                force=payload.force,
            )
        )
    except NotEnoughDocumentsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    jobs = AIJobRepository(db)

    active_job = jobs.find_active(max_age_seconds=settings.ai_job_timeout_seconds)

    if active_job:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"AI job {active_job.id} is still {active_job.status}.",
        )

    try:
        job = jobs.create(
            payload.model_dump(), max_age_seconds=settings.ai_job_timeout_seconds
        )
    except AIJobAlreadyActiveError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An AI job is already running.",
        ) from exc
    background_tasks.add_task(run_ai_job, job.id, session_factory)

    return job


@router.get(
    "/process/{job_id}",
    response_model=AIJobRead,
    dependencies=[Depends(require_admin)],
)
def get_job(job_id: str, db: DbSession) -> AIJobRead:
    """A job's status and result; admin only, since `error` may hold internal details."""
    job = AIJobRepository(db).get(job_id)

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="AI job not found.",
        )

    return job


@router.get(
    "/topics",
    response_model=list[TopicRead],
)
def list_topics(db: DbSession) -> list[TopicRead]:
    """Every topic found so far, with its size, keywords and most typical articles."""

    topics = TopicRepository(db).list_with_sizes()

    article_ids = {
        article_id
        for topic, _ in topics
        for article_id in topic.representative_article_ids
    }
    articles = {
        article.id: article
        for article in ArticleRepository(db).get_many(article_ids)
    }

    return [
        TopicRead(
            id=topic.id,
            label=topic.label,
            size=size,
            keywords=topic.keywords,
            representative_articles=[
                RepresentativeArticle(
                    id=article.id,
                    title=article.title,
                    url=article.url,
                )
                for article_id in topic.representative_article_ids
                if (article := articles.get(article_id))
            ],
            updated_at=topic.updated_at,
        )
        for topic, size in topics
    ]
