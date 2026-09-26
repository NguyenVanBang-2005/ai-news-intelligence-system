from fastapi import APIRouter, Query

from app.api.deps import DbSession
from app.schemas.ingestion import IngestionResult
from app.services.ingestion import IngestionService

router = APIRouter(prefix="/ingestion", tags=["ingestion"])


@router.post("/run", response_model=IngestionResult)
def run_ingestion(
    db: DbSession, source_id: int | None = Query(default=None, ge=1)
) -> IngestionResult:
    return IngestionService(db).run(source_id)
