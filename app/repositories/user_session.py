from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.user import UserSession


class UserSessionRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, *, user_id: int, token_hash: str, expires_at: datetime) -> UserSession:
        session = UserSession(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
        self.db.add(session)
        self.db.commit()
        return session

    def get_unexpired(self, token_hash: str, now: datetime) -> UserSession | None:
        """The session for this token hash, unless it has expired."""
        statement = select(UserSession).where(
            UserSession.token_hash == token_hash, UserSession.expires_at > now
        )
        return self.db.scalar(statement)

    def delete_by_token_hash(self, token_hash: str) -> None:
        self.db.execute(delete(UserSession).where(UserSession.token_hash == token_hash))
        self.db.commit()

    def delete_for_user_except(self, user_id: int, keep_token_hash: str) -> int:
        """Remove every session of the user but the one with `keep_token_hash`."""
        result = self.db.execute(
            delete(UserSession).where(
                UserSession.user_id == user_id, UserSession.token_hash != keep_token_hash
            )
        )
        self.db.commit()
        return result.rowcount

    def delete_expired(self, now: datetime) -> int:
        """Remove every expired session; returns how many were removed."""
        result = self.db.execute(delete(UserSession).where(UserSession.expires_at <= now))
        self.db.commit()
        return result.rowcount
