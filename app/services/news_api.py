"""News search through the GNews API (https://gnews.io), returned as feed items."""

import re
from datetime import UTC, datetime

import httpx
from dateutil import parser as date_parser

from app.core.config import settings
from app.services.feed import TITLE_MAX_CHARS, FeedItem, valid_article_url
from app.services.text_cleaning import clean_text, truncate

# GNews cuts article content and appends a marker such as "... [2345 chars]".
TRUNCATION_MARKER = re.compile(r"\s*(\.\.\.|…)?\s*\[\d+ chars\]\s*$")


class NewsApiNotConfiguredError(RuntimeError):
    pass


class NewsApiError(RuntimeError):
    """The API call failed. The message never contains the API key."""


class GNewsClient:
    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str,
        timeout_seconds: float,
        transport: httpx.BaseTransport | None = None,
    ):
        self.api_key = api_key
        self.search_url = f"{base_url.rstrip('/')}/search"
        self.timeout_seconds = timeout_seconds
        # Injectable so tests can answer without the real API.
        self.transport = transport

    @classmethod
    def from_settings(cls) -> "GNewsClient":
        return cls(
            api_key=settings.news_api_key,
            base_url=settings.news_api_base_url,
            timeout_seconds=settings.request_timeout_seconds,
        )

    def search(self, query: str, *, language: str, max_items: int) -> list[FeedItem]:
        """The newest articles matching `query`, at most `max_items`."""

        if not self.api_key:
            raise NewsApiNotConfiguredError("Set NEWS_API_KEY to use news_api sources")

        params = {
            "q": query,
            "lang": language,
            "max": max_items,
            "sortby": "publishedAt",
            "apikey": self.api_key,
        }

        try:
            with httpx.Client(timeout=self.timeout_seconds, transport=self.transport) as client:
                response = client.get(self.search_url, params=params)
                response.raise_for_status()
                articles = response.json()["articles"]
        except httpx.HTTPStatusError as exc:
            # The request URL contains the API key, so it must not reach the message.
            raise NewsApiError(
                f"News API returned HTTP {exc.response.status_code}"
            ) from None
        except httpx.HTTPError as exc:
            raise NewsApiError(f"News API could not be reached ({type(exc).__name__})") from None
        except (ValueError, KeyError, TypeError):
            raise NewsApiError("News API returned an unexpected response") from None

        return [
            item
            for raw_article in articles[:max_items]
            if (item := self._to_item(raw_article)) is not None
        ]

    @staticmethod
    def _to_item(raw_article: dict) -> FeedItem | None:
        url = valid_article_url(raw_article.get("url"))
        title = truncate(clean_text(raw_article.get("title"), multiline=False), TITLE_MAX_CHARS)

        if url is None or not title:
            return None

        content = TRUNCATION_MARKER.sub("", clean_text(raw_article.get("content")))
        description = clean_text(raw_article.get("description"))

        return FeedItem(
            title=title,
            url=url,
            author=None,
            # The longer of the two; full-text extraction may replace it later.
            content=truncate(
                max(content, description, key=len),
                settings.max_article_content_chars,
            ),
            published_at=_parse_date(raw_article.get("publishedAt")),
        )


def _parse_date(raw_date: object) -> datetime | None:
    if not isinstance(raw_date, str):
        return None

    try:
        published_at = date_parser.isoparse(raw_date)
    except (ValueError, OverflowError):
        return None

    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=UTC)

    return published_at.astimezone(UTC)
