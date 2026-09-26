from pydantic import BaseModel


class IngestionResult(BaseModel):
    sources_processed: int
    articles_seen: int
    articles_created: int
    duplicates_skipped: int
    errors: list[str]

