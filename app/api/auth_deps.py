"""Dependencies for signed-in users: current user, CSRF check and sign-in rate limits."""

from typing import Annotated
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request, status

from app.api.deps import DbSession, rate_limit_key
from app.core.config import settings
from app.models.user import User
from app.services.auth import resolve_session
from app.services.rate_limit import SlidingWindowRateLimiter

# Header the AINIS UI sends with every cookie-authenticated change (see require_csrf_safe_request).
CSRF_HEADER = "X-Requested-With"
CSRF_HEADER_VALUE = "ainis"

# In memory, per process (see app/services/rate_limit.py): exact with one worker only.
# The window is read from settings when the limiter is created, i.e. at import time.
login_failure_limiter = SlidingWindowRateLimiter(window_seconds=settings.auth_login_window_seconds)
register_rate_limiter = SlidingWindowRateLimiter(window_seconds=3600)


def _origin_matches_host(origin: str, host: str | None) -> bool:
    """True when the Origin header names the same host (and port) the request was sent to."""
    return host is not None and urlsplit(origin).netloc.lower() == host.lower()


def require_csrf_safe_request(request: Request) -> None:
    """Block cross-site requests. Every endpoint that changes data and accepts the session
    cookie must depend on this too.

    (a) An Origin header, when present, must match the request's Host.
    (b) A request carrying the session cookie must send "X-Requested-With: ainis", which a
        plain cross-site form or link cannot add.
    """
    origin = request.headers.get("origin")
    if origin is not None and not _origin_matches_host(origin, request.headers.get("host")):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Cross-site request refused.")
    uses_cookie = settings.session_cookie_name in request.cookies
    if uses_cookie and request.headers.get(CSRF_HEADER) != CSRF_HEADER_VALUE:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail=f"Missing {CSRF_HEADER}: {CSRF_HEADER_VALUE} header.",
        )


def get_current_user(request: Request, db: DbSession) -> User:
    """The signed-in user from the session cookie, or 401."""
    token = request.cookies.get(settings.session_cookie_name)
    user = resolve_session(db, token) if token else None
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Not signed in.")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


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


def login_failure_key(request: Request, username: str) -> str:
    """Failed logins are counted per username and client address together."""
    return f"{username}|{rate_limit_key(request)}"
