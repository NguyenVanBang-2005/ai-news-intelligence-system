from fastapi import APIRouter, HTTPException, Query

from app.api.deps import DbSession
from app.repositories.article import ArticleRepository
from app.schemas.article import ArticlePage, ArticleRead

router = APIRouter(prefix="/articles", tags=["articles"])


@router.get("", response_model=ArticlePage)
def list_articles(
    db: DbSession,
    topic: str | None = None,
    status: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> ArticlePage:
    items, total = ArticleRepository(db).list(
        topic=topic, status=status, limit=limit, offset=offset
    )
    return ArticlePage(items=items, total=total, limit=limit, offset=offset)


@router.get("/{article_id}", response_model=ArticleRead)
def get_article(article_id: int, db: DbSession) -> ArticleRead:
    article = ArticleRepository(db).get(article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")
    return article

