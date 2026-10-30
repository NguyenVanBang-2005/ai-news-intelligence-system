"""Short, public-safe messages for why a source failed to sync.

Source.last_error is returned by the public GET /sources, so it never holds the exception
text: that may contain the feed URL, a hostname, an IP address or server output.
"""

import httpx
from sqlalchemy.exc import SQLAlchemyError

from app.models.source import LAST_ERROR_MAX_CHARS
from app.services.feed import FeedTooLargeError, UnsupportedFeedError
from app.services.news_api import NewsApiError, NewsApiNotConfiguredError
from app.services.safe_http import (
    ResponseTooLargeError,
    TooManyRedirectsError,
    UnsafeFeedUrlError,
)

UNEXPECTED_ERROR_MESSAGE = "Unexpected error"

# Checked in order with isinstance, so subclasses come before their base classes
# (httpx.TimeoutException and httpx.ConnectError are both httpx.RequestError).
ERROR_MESSAGES: tuple[tuple[type[BaseException], str], ...] = (
    (UnsupportedFeedError, "Link returns HTML or another document, not RSS/Atom"),
    (FeedTooLargeError, "Feed is larger than the size limit"),
    (ResponseTooLargeError, "Response is larger than the size limit"),
    (UnsafeFeedUrlError, "Blocked non-public or unresolvable address"),
    (TooManyRedirectsError, "Too many redirects"),
    (httpx.TimeoutException, "Request timed out"),
    (httpx.ConnectError, "Could not connect to the server"),
    (httpx.HTTPStatusError, "Server answered with an error status"),
    (httpx.RequestError, "Network error while fetching"),
    (NewsApiNotConfiguredError, "News API key is not configured"),
    (NewsApiError, "News API request failed"),
    (SQLAlchemyError, "Database error while saving articles"),
)


def short_error_message(exc: BaseException) -> str:
    """Error type and a fixed message for it, at most LAST_ERROR_MAX_CHARS characters."""
    message = next(
        (text for error_type, text in ERROR_MESSAGES if isinstance(exc, error_type)),
        UNEXPECTED_ERROR_MESSAGE,
    )
    return f"{type(exc).__name__}: {message}"[:LAST_ERROR_MAX_CHARS]
