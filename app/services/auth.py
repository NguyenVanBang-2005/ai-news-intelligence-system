"""Accounts and sign-in sessions.

A session token is random, given to the browser once (as a cookie) and stored only as
its SHA-256, so a leaked database does not let anyone sign in.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.user import ROLE_USER, User
from app.repositories.user import UsernameTakenError, UserRepository
from app.repositories.user_session import UserSessionRepository
from app.services.passwords import hash_password, verify_dummy, verify_password

__all__ = [
    "UsernameTakenError",
    "authenticate",
    "create_session",
    "hash_token",
    "register_user",
    "resolve_session",
    "revoke_session",
]

TOKEN_BYTES = 32


def hash_token(token: str) -> str:
    """The SHA-256 hex digest stored in place of the session token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def register_user(db: Session, username: str, password: str) -> User:
    """Create an account. Self-registration always gets the "user" role."""
    return UserRepository(db).create(
        username=username, password_hash=hash_password(password), role=ROLE_USER
    )


def authenticate(db: Session, username: str, password: str) -> User | None:
    """The active user with these credentials, or None (same work either way)."""
    user = UserRepository(db).get_by_username(username)
    if user is None:
        verify_dummy(password)
        return None
    if not verify_password(password, user.password_hash) or not user.is_active:
        return None
    return user


def create_session(db: Session, user: User) -> str:
    """Start a session and return its raw token; this is the only time it is known."""
    now = datetime.now(UTC)
    sessions = UserSessionRepository(db)
    sessions.delete_expired(now)  # lazy clean-up, once per login
    token = secrets.token_urlsafe(TOKEN_BYTES)
    sessions.create(
        user_id=user.id,
        token_hash=hash_token(token),
        expires_at=now + timedelta(hours=settings.session_ttl_hours),
    )
    UserRepository(db).set_last_login(user, now)
    return token


def resolve_session(db: Session, token: str) -> User | None:
    """The user of an unexpired session whose account is still active, else None."""
    session = UserSessionRepository(db).get_unexpired(hash_token(token), datetime.now(UTC))
    if session is None:
        return None
    user = UserRepository(db).get(session.user_id)
    if user is None or not user.is_active:
        return None
    return user


def revoke_session(db: Session, token: str) -> None:
    """End the session for this token; unknown tokens are ignored."""
    UserSessionRepository(db).delete_by_token_hash(hash_token(token))
