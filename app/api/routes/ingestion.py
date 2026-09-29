from fastapi import APIRouter, Query

from app.api.deps import DbSession
from app.schemas.ingestion import IngestionResult
from app.services.ingestion import IngestionService

router = APIRouter(prefix="/ingestion", tags=["ingestion"])


@router.post(
    "/run",
    response_model=IngestionResult,
    description=(
        "Fetch RSS/Atom from the saved source.feed_url. Select a source_id or omit it "
        "to process all active sources. This endpoint does not accept an article URL. "
        "Per-source failures are returned in errors even when the batch returns HTTP 200."
    ),
)
def run_ingestion(
    db: DbSession, source_id: int | None = Query(default=None, ge=1)
) -> IngestionResult:
    return IngestionService(db).run(source_id)
