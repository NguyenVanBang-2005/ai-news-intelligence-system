from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.source import Source
from app.schemas.source import SourceCreate


class SourceRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, payload: SourceCreate) -> Source:
        source = Source(
            name=payload.name.strip(),
            feed_url=str(payload.feed_url),
            language=payload.language.lower(),
        )
        self.db.add(source)
        self.db.commit()
        self.db.refresh(source)
        return source

    def list(self, active_only: bool = False) -> list[Source]:
        statement = select(Source).order_by(Source.name)
        if active_only:
            statement = statement.where(Source.is_active.is_(True))
        return list(self.db.scalars(statement))

    def get(self, source_id: int) -> Source | None:
        return self.db.get(Source, source_id)

    def delete(self, source: Source) -> None:
        self.db.delete(source)
        self.db.commit()

