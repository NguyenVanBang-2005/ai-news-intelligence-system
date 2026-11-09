from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.user import User


class UsernameTakenError(Exception):
    """Another account already uses this username."""


class UserRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, user_id: int) -> User | None:
        return self.db.get(User, user_id)

    def get_by_username(self, username: str) -> User | None:
        return self.db.scalar(select(User).where(User.username == username))

    def create(self, *, username: str, password_hash: str, role: str) -> User:
        """Insert the account, or raise UsernameTakenError if the name is in use."""
        user = User(username=username, password_hash=password_hash, role=role)
        self.db.add(user)
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise UsernameTakenError from exc
        return user

    def grant_role_and_activate(self, user: User, *, role: str, password_hash: str | None) -> None:
        """Give the user `role` and re-enable the account; replace the hash only if given."""
        user.role = role
        user.is_active = True
        if password_hash is not None:
            user.password_hash = password_hash
        self.db.commit()

    def set_last_login(self, user: User, when: datetime) -> None:
        user.last_login_at = when
        self.db.commit()
