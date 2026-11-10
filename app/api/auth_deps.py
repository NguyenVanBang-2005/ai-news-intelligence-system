"""Dependencies for signed-in users: current user, require_user and sign-in rate limits."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from app.api.deps import (
    DbSession,
    check_csrf_if_state_changing,
    find_session_user,
    rate_limit_key,
    require_csrf_safe_request,
)
from app.core.config import settings
from app.models.user import User
from app.services.rate_limit import SlidingWindowRateLimiter

# require_csrf_safe_request lives in app/api/deps.py (require_admin needs it); re-exported here.
__all__ = [
    "CurrentUser",
    "get_current_user",
    "limit_login_attempts",
    "limit_register_rate",
    "login_failure_key",
    "require_csrf_safe_request",
    "require_user",
]

# In memory, per process (see app/services/rate_limit.py): exact with one worker only.
# The window is read from settings when the limiter is created, i.e. at import time.
login_failure_limiter = SlidingWindowRateLimiter(window_seconds=settings.auth_login_window_seconds)
login_ip_limiter = SlidingWindowRateLimiter(window_seconds=settings.login_ip_window_seconds)
register_rate_limiter = SlidingWindowRateLimiter(window_seconds=3600)


def get_current_user(request: Request, db: DbSession) -> User:
    """The signed-in user from the session cookie, or 401."""
    user = find_session_user(request, db)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Not signed in.")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_user(request: Request, user: CurrentUser) -> User:
    """Any signed-in user ("user" or "admin"), else 401. A POST/PUT/PATCH/DELETE must also
    pass require_csrf_safe_request (403). For endpoints added later."""
    check_csrf_if_state_changing(request)
    return user


def limit_register_rate(request: Request) -> None:
    """At most AUTH_REGISTER_PER_HOUR registration attempts per client address."""
    retry_after = register_rate_limiter.hit(
        rate_limit_key(request), settings.auth_register_per_hour
    )
    if retry_after is not None:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many registrations. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )


def limit_login_attempts(request: Request) -> None:
    """At most LOGIN_IP_MAX_ATTEMPTS logins per client address per LOGIN_IP_WINDOW_SECONDS.

    Every attempt counts, also a successful one (never forgotten), and the check runs
    before the password is hashed: a refused attempt costs no scrypt.
    """
    retry_after = login_ip_limiter.hit(rate_limit_key(request), settings.login_ip_max_attempts)
    if retry_after is not None:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )


def login_failure_key(request: Request, username: str) -> str:
    """Failed logins are counted per username and client address together."""
    return f"{username}|{rate_limit_key(request)}"
