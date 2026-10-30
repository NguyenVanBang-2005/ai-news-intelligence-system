from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.source import Source
from app.schemas.source import SourceCreate

# Placeholder feed URL of the source for user-submitted links (never fetched).
USER_LINKS_FEED_URL = "user-submitted://links"


class SourceRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, payload: SourceCreate) -> Source:
        source = Source(
            name=payload.name.strip(),
            type=payload.type,
            feed_url=str(payload.feed_url) if payload.feed_url else None,
            query=payload.query.strip() if payload.query else None,
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

    def get_or_create_user_links(self) -> Source:
        """The source that holds articles users submitted by link.

        It is inactive, so RSS ingestion never tries to fetch its placeholder URL.
        """
        source = self.db.scalar(select(Source).where(Source.feed_url == USER_LINKS_FEED_URL))
        if source is None:
            source = Source(
                name="User-submitted links",
                feed_url=USER_LINKS_FEED_URL,
                is_active=False,
            )
            self.db.add(source)
            self.db.commit()
        return source

    def get(self, source_id: int) -> Source | None:
        return self.db.get(Source, source_id)

    def set_active(self, source: Source, is_active: bool) -> Source:
        """Turn ingestion of this source on or off."""
        source.is_active = is_active
        self.db.commit()
        self.db.refresh(source)
        return source

    def delete(self, source: Source) -> None:
        self.db.delete(source)
        self.db.commit()

