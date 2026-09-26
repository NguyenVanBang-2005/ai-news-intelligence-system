import ipaddress
import socket
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlparse

import feedparser
import httpx
from dateutil import parser as date_parser


@dataclass(frozen=True)
class FeedItem:
    title: str
    url: str
    author: str | None
    content: str
    published_at: datetime | None


class UnsafeFeedUrlError(ValueError):
    pass


def validate_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise UnsafeFeedUrlError("Only public HTTP(S) feed URLs are accepted")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443)
    except socket.gaierror as exc:
        raise UnsafeFeedUrlError("Feed hostname could not be resolved") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise UnsafeFeedUrlError("Private or local feed addresses are not accepted")


class FeedClient:
    def __init__(self, timeout_seconds: float):
        self.timeout_seconds = timeout_seconds

    def fetch(self, url: str, max_items: int) -> list[FeedItem]:
        validate_public_url(url)
        with httpx.Client(timeout=self.timeout_seconds, follow_redirects=False) as client:
            response = client.get(url, headers={"User-Agent": "AI-News-Intelligence/0.1"})
            response.raise_for_status()
        parsed = feedparser.parse(response.content)
        return [self._to_item(entry) for entry in parsed.entries[:max_items] if entry.get("link")]

    @staticmethod
    def _to_item(entry: dict) -> FeedItem:
        raw_date = entry.get("published") or entry.get("updated")
        published_at = None
        if raw_date:
            try:
                published_at = date_parser.parse(raw_date)
                if published_at.tzinfo is None:
                    published_at = published_at.replace(tzinfo=UTC)
            except (TypeError, ValueError, OverflowError):
                pass
        content = entry.get("summary", "")
        if entry.get("content"):
            content = entry["content"][0].get("value", content)
        return FeedItem(
            title=entry.get("title", "Untitled").strip(),
            url=entry["link"].strip(),
            author=entry.get("author"),
            content=content.strip(),
            published_at=published_at,
        )

