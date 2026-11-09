import secrets
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.db.session import get_db, get_session_factory
from app.models.user import ROLE_ADMIN, User
from app.services.auth import resolve_session
from app.services.rate_limit import SlidingWindowRateLimiter

DbSession = Annotated[Session, Depends(get_db)]

SessionFactory = Annotated[sessionmaker[Session], Depends(get_session_factory)]

ADMIN_TOKEN_HEADER = "X-Admin-Token"
# auto_error=False: a missing header is answered below with 401, not FastAPI's 403.
# Kept for the OpenAPI docs; whether the header is present is read from request.headers,
# because APIKeyHeader turns an empty header into None.
admin_token_header = APIKeyHeader(name=ADMIN_TOKEN_HEADER, auto_error=False)

# Header the AINIS UI sends with every cookie-authenticated change (see require_csrf_safe_request).
CSRF_HEADER = "X-Requested-With"
CSRF_HEADER_VALUE = "ainis"
STATE_CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


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


def find_session_user(request: Request, db: Session) -> User | None:
    """The user of a valid session cookie (unexpired, account active), else None."""
    token = request.cookies.get(settings.session_cookie_name)
    return resolve_session(db, token) if token else None


def check_csrf_if_state_changing(request: Request) -> None:
    """Cookie-authenticated POST/PUT/PATCH/DELETE must pass require_csrf_safe_request."""
    if request.method in STATE_CHANGING_METHODS:
        require_csrf_safe_request(request)


def _check_admin_token(token: str | None) -> None:
    """The service-token check: 503 when no token is configured, 401 when missing or wrong."""
    expected = settings.admin_api_token
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin endpoints are disabled: ADMIN_API_TOKEN is not configured.",
        )

    # Compared as bytes: compare_digest rejects non-ASCII str.
    if token is None or not secrets.compare_digest(
        token.encode("utf-8"), expected.encode("utf-8")
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid X-Admin-Token header.",
        )


def require_admin(
    request: Request,
    db: DbSession,
    _documented_token: Annotated[str | None, Security(admin_token_header)],
) -> None:
    """Guard for write and costly endpoints, decided in this order:

    a. X-Admin-Token header present (even empty): only the token counts (503 if unset,
       401 if wrong); cookies are ignored and no CSRF check is made.
    b. No header, valid session cookie: role "admin" passes, role "user" gets 403; a
       POST/PUT/PATCH/DELETE must also pass require_csrf_safe_request (403).
    c. No header, no valid session (none, expired, account disabled): same as (a) with
       no token, so the answer stays 503/401.
    """
    token = request.headers.get(ADMIN_TOKEN_HEADER)
    if token is None:
        user = find_session_user(request, db)
        if user is not None:
            check_csrf_if_state_changing(request)
            if user.role != ROLE_ADMIN:
                raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Admin role required")
            return
    _check_admin_token(token)


# Per process: each worker counts on its own (see app/services/rate_limit.py).
search_rate_limiter = SlidingWindowRateLimiter(window_seconds=60)


def rate_limit_key(request: Request) -> str:
    """The key a request is counted under: the address of the socket peer, or "unknown"."""

    # Forwarding headers are written by the client itself; trusting them would
    # let anyone get a fresh bucket per request. Nothing sits in front of the API.
    return request.client.host if request.client else "unknown"


def _enforce_search_limit(key: str, limit: int) -> None:
    """Count one search under `key`; 429 with Retry-After once `limit` per minute is reached."""
    retry_after = search_rate_limiter.hit(key, limit)
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many searches. Please wait a moment and try again.",
            headers={"Retry-After": str(retry_after)},
        )


def limit_search_rate(request: Request) -> None:
    """At most AI_SEARCH_RATE_PER_MINUTE public searches per client IP."""
    _enforce_search_limit(rate_limit_key(request), settings.ai_search_rate_per_minute)


def limit_search_rate_by_role(request: Request, db: DbSession) -> None:
    """Signed-in users (any role) get AI_SEARCH_USER_RATE_PER_MINUTE per user id;
    everyone else gets the anonymous per-IP limit. X-Admin-Token plays no part."""
    user = find_session_user(request, db)
    if user is None:
        limit_search_rate(request)
        return
    # The "user:" prefix keeps these keys apart from IP addresses.
    _enforce_search_limit(f"user:{user.id}", settings.ai_search_user_rate_per_minute)
