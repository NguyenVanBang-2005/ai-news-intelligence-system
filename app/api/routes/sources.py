from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbSession, require_admin
from app.repositories.source import SourceRepository
from app.schemas.source import SourceCreate, SourceRead, SourceUpdate

router = APIRouter(prefix="/sources", tags=["sources"])


@router.post(
    "",
    response_model=SourceRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
def create_source(payload: SourceCreate, db: DbSession) -> SourceRead:
    try:
        return SourceRepository(db).create(payload)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Source name or feed URL already exists"
        ) from exc


@router.get("", response_model=list[SourceRead])
def list_sources(db: DbSession) -> list[SourceRead]:
    return SourceRepository(db).list()


@router.patch(
    "/{source_id}",
    response_model=SourceRead,
    dependencies=[Depends(require_admin)],
)
def update_source(source_id: int, payload: SourceUpdate, db: DbSession) -> SourceRead:
    """Turn a source on or off; inactive sources are skipped by ingestion."""
    repository = SourceRepository(db)
    source = repository.get(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return repository.set_active(source, payload.is_active)


@router.delete(
    "/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_admin)],
)
def delete_source(source_id: int, db: DbSession) -> Response:
    repository = SourceRepository(db)
    source = repository.get(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    repository.delete(source)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
