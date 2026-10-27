import logging
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlparse

import feedparser
import httpx
from dateutil import parser as date_parser

from app.core.config import settings
from app.services.safe_http import (
    ResponseTooLargeError,
    make_client,
    open_stream,
    read_limited,
)
from app.services.text_cleaning import clean_text, truncate

# Keep in sync with the Article column sizes.
TITLE_MAX_CHARS = 500
AUTHOR_MAX_CHARS = 200
URL_MAX_CHARS = 1500
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FeedItem:
    title: str
    url: str
    author: str | None
    content: str
    published_at: datetime | None


class FeedTooLargeError(ValueError):
    pass


class UnsupportedFeedError(ValueError):
    """The response is not a recognized RSS/Atom document."""

    pass


def valid_article_url(raw: object) -> str | None:
    """Return the stripped link if it is a plain HTTP(S) URL that fits the column, else None."""
    if not isinstance(raw, str):
        return None
    url = raw.strip()
    if not url or len(url) > URL_MAX_CHARS:
        return None
    try:
        parsed = urlparse(url)
        parsed.port  # noqa: B018  (raises ValueError on an invalid port)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    return url


class FeedClient:
    def __init__(
        self,
        timeout_seconds: float,
        transport: httpx.BaseTransport | None = None,
        max_feed_bytes: int | None = None,
        max_content_chars: int | None = None,
    ):
        self.timeout_seconds = timeout_seconds
        # Injectable so tests can serve fixtures without real network calls.
        self.transport = transport
        self.max_feed_bytes = max_feed_bytes or settings.max_feed_bytes
        self.max_content_chars = max_content_chars or settings.max_article_content_chars

    def fetch(self, url: str, max_items: int) -> list[FeedItem]:
        headers = {"User-Agent": "AI-News-Intelligence/0.1"}
        with make_client(self.timeout_seconds, self.transport) as client:
            response = open_stream(client, url, headers, settings.article_max_redirects)
            with closing(response):
                response.raise_for_status()
                body = self._read_limited(response)
                content_type = response.headers.get("content-type", "unknown")
        parsed = feedparser.parse(body)
        # feedparser accepts HTML without raising; entries=[] alone is not validation.
        # Inspect the document, not just Content-Type: some RSS servers mislabel XML.
        if not parsed.version:
            raise UnsupportedFeedError(
                f"Expected an RSS/Atom feed, received an unrecognized document "
                f"(HTTP {response.status_code}, Content-Type: {content_type}). "
                "HTML topic pages and individual article URLs are not supported. "
                "Set the saved source.feed_url to the publisher's RSS/Atom URL."
            )
        # Entries with an empty title or an invalid link are dropped silently: they are
        # not counted in articles_seen. max_items caps entries examined, not entries kept.
        entries = parsed.entries[:max_items]
        items = [item for entry in entries if (item := self._to_item(entry)) is not None]
        logger.info(
            "Feed parsed: HTTP=%s content_type=%s format=%s entries=%d "
            "examined=%d accepted=%d skipped_invalid_title_or_url=%d",
            response.status_code, content_type, parsed.version, len(parsed.entries),
            len(entries), len(items), len(entries) - len(items),
        )
        return items

    def _read_limited(self, response: httpx.Response) -> bytes:
        """Read the (decoded) body, aborting as soon as it exceeds the byte limit."""
        try:
            return read_limited(response, self.max_feed_bytes)
        except ResponseTooLargeError as exc:
            raise FeedTooLargeError(f"Feed exceeds {self.max_feed_bytes} bytes") from exc

    def _to_item(self, entry: dict) -> FeedItem | None:
        url = valid_article_url(entry.get("link"))
        title = truncate(clean_text(entry.get("title"), multiline=False), TITLE_MAX_CHARS)
        if url is None or not title:
            return None
        raw_date = entry.get("published") or entry.get("updated")
        published_at = None
        if raw_date:
            try:
                published_at = date_parser.parse(raw_date)
                if published_at.tzinfo is None:
                    published_at = published_at.replace(tzinfo=UTC)
                published_at = published_at.astimezone(UTC)
            except (TypeError, ValueError, OverflowError):
                pass
        # Prefer the full <content> body; fall back to <summary>/<description>.
        content = ""
        for candidate in (*entry.get("content", []), {"value": entry.get("summary")}):
            content = clean_text(candidate.get("value"))
            if content:
                break
        # Some feeds repeat the headline as the body; that is not real content.
        if content.casefold() == title.casefold():
            content = ""
        content = truncate(content, self.max_content_chars)
        author = truncate(clean_text(entry.get("author"), multiline=False), AUTHOR_MAX_CHARS)
        return FeedItem(
            title=title,
            url=url,
            author=author or None,
            content=content,
            published_at=published_at,
        )
