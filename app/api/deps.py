import secrets
from ipaddress import IPv4Address, IPv6Address, ip_address
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


def _parse_ip(value: str) -> IPv4Address | IPv6Address | None:
    try:
        address = ip_address(value.strip())
    except ValueError:
        return None
    # "::ffff:172.28.0.5" is the IPv4 address of a dual-stack socket.
    if isinstance(address, IPv6Address) and address.ipv4_mapped:
        return address.ipv4_mapped
    return address


def _is_trusted(address: IPv4Address | IPv6Address) -> bool:
    return any(address in network for network in settings.trusted_proxy_cidrs)


def client_ip(request: Request) -> str:
    """The address of the real client, never one the client claims about itself.

    X-Forwarded-For is only read when the socket peer is a trusted proxy
    (TRUSTED_PROXY_CIDRS). It is then walked right to left, the order hops appended it,
    skipping trusted proxies; the first untrusted address is the client. Everything left of
    it could have been written by the client, so it is never used. An empty or malformed
    header, or one with only trusted hops, yields the peer.
    """

    peer = request.client.host if request.client else "unknown"
    peer_address = _parse_ip(peer)

    if peer_address is None or not _is_trusted(peer_address):
        return peer

    forwarded = ",".join(request.headers.getlist("x-forwarded-for"))

    for hop in reversed(forwarded.split(",")):
        address = _parse_ip(hop)
        if address is None:
            return peer  # cannot tell who wrote the rest: fall back to the proxy
        if not _is_trusted(address):
            return str(address)

    return peer


def limit_search_rate(request: Request) -> None:
    """At most AI_SEARCH_RATE_PER_MINUTE public searches per client IP."""

    retry_after = search_rate_limiter.hit(client_ip(request), settings.ai_search_rate_per_minute)

    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many searches. Please wait a moment and try again.",
            headers={"Retry-After": str(retry_after)},
        )
