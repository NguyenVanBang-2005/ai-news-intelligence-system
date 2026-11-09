from datetime import UTC, datetime

from sqlalchemy import Boolean, ForeignKey, String, Text, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.db.types import UTCDateTime

ROLE_USER = "user"
ROLE_ADMIN = "admin"


def _now() -> datetime:
    return datetime.now(UTC)


class User(Base):
    """An account that signs in with a username and password."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Always stored lower-case (see app/schemas/auth.py).
    username: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    # "scrypt$n$r$p$salt$hash" (see app/services/passwords.py); never the password itself.
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(10), default=ROLE_USER, server_default=ROLE_USER)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class UserSession(Base):
    """A signed-in browser. Only the SHA-256 of the cookie token is stored."""

    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
