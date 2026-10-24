"""Rate limit of POST /ai/search: keyed by the socket peer only, never by request headers.

No database or network: the dependency is called with requests built from ASGI scopes.
"""

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api.deps import limit_search_rate, rate_limit_key, search_rate_limiter
from app.core.config import settings

PEER = "203.0.113.7"
LIMIT = 30


@pytest.fixture(autouse=True)
def default_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the documented default so a local .env cannot change the expected counts."""
    monkeypatch.setattr(settings, "ai_search_rate_per_minute", LIMIT)


def build_request(peer: str | None, headers: dict[str, str] | None = None) -> Request:
    """A bare HTTP request; peer=None leaves out the ASGI "client" entry."""
    pairs = (headers or {}).items()
    raw_headers = [(name.lower().encode(), value.encode()) for name, value in pairs]
    scope = {"type": "http", "method": "POST", "path": "/api/v1/ai/search", "headers": raw_headers}
    if peer is not None:
        scope["client"] = (peer, 40000)
    return Request(scope)


def statuses_for(requests: list[Request]) -> list[int]:
    """Run each request through the limiter and collect 200 (allowed) or the error status."""
    statuses = []
    for request in requests:
        try:
            limit_search_rate(request)
            statuses.append(200)
        except HTTPException as exc:
            statuses.append(exc.status_code)
    return statuses


def test_forwarding_headers_are_ignored_and_share_one_bucket() -> None:
    requests = [
        build_request(PEER, {"X-Forwarded-For": f"198.51.100.{n}", "X-Real-IP": f"192.0.2.{n}"})
        for n in range(1, LIMIT + 2)
    ]

    statuses = statuses_for(requests)

    assert statuses[:LIMIT] == [200] * LIMIT
    assert statuses[LIMIT] == 429
    assert rate_limit_key(requests[0]) == PEER


def test_the_429_carries_retry_after() -> None:
    for _ in range(LIMIT):
        limit_search_rate(build_request(PEER))

    with pytest.raises(HTTPException) as caught:
        limit_search_rate(build_request(PEER))

    assert caught.value.status_code == 429
    assert int(caught.value.headers["Retry-After"]) >= 1


def test_a_request_without_client_uses_the_unknown_bucket() -> None:
    request = build_request(None)

    assert request.client is None
    assert rate_limit_key(request) == "unknown"
    assert statuses_for([build_request(None) for _ in range(LIMIT + 1)]) == [200] * LIMIT + [429]
    # Another peer is counted separately, so the "unknown" bucket does not block it.
    assert statuses_for([build_request(PEER)]) == [200]
    assert search_rate_limiter.hit("unknown", LIMIT) is not None
