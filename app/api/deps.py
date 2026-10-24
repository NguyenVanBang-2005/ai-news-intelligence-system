import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.db.session import get_db, get_session_factory
from app.services.rate_limit import SlidingWindowRateLimiter

DbSession = Annotated[Session, Depends(get_db)]

SessionFactory = Annotated[sessionmaker[Session], Depends(get_session_factory)]

# auto_error=False: a missing header is answered below with 401, not FastAPI's 403.
admin_token_header = APIKeyHeader(name="X-Admin-Token", auto_error=False)


def require_admin(token: Annotated[str | None, Security(admin_token_header)]) -> None:
    """Guard for write and costly endpoints. Fails closed when no token is configured."""

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


# Per process: each worker counts on its own (see app/services/rate_limit.py).
search_rate_limiter = SlidingWindowRateLimiter(window_seconds=60)


def rate_limit_key(request: Request) -> str:
    """The key a request is counted under: the address of the socket peer, or "unknown"."""

    # Forwarding headers are written by the client itself; trusting them would
    # let anyone get a fresh bucket per request. Nothing sits in front of the API.
    return request.client.host if request.client else "unknown"


def limit_search_rate(request: Request) -> None:
    """At most AI_SEARCH_RATE_PER_MINUTE public searches per client IP."""

    retry_after = search_rate_limiter.hit(
        rate_limit_key(request), settings.ai_search_rate_per_minute
    )

    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many searches. Please wait a moment and try again.",
            headers={"Retry-After": str(retry_after)},
        )
