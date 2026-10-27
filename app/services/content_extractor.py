import re
from contextlib import closing
from dataclasses import dataclass

import httpx
import trafilatura

from app.services.safe_http import make_client, open_stream, read_limited


@dataclass(frozen=True)
class ExtractedPage:
    title: str | None
    text: str


class ArticleContentExtractor:
    """Download and extract the main textual content of an article."""

    def __init__(
        self,
        timeout_seconds: float,
        max_download_bytes: int,
        max_redirects: int,
        transport: httpx.BaseTransport | None = None,
    ):
        self.transport = transport
        self.timeout_seconds = timeout_seconds
        self.max_download_bytes = max_download_bytes
        self.max_redirects = max_redirects

    def extract_from_url(self, url: str) -> str | None:
        """Return clean article text, or None if extraction fails."""

        page = self.extract_page(url)

        return page.text if page else None

    def extract_page(self, url: str) -> ExtractedPage | None:
        """Return the page title and clean article text, or None if extraction fails."""

        html = self._download_html(url)

        if html is None:
            return None

        text = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=False,
            include_links=False,
            favor_precision=True,
            output_format="txt",
        )

        if not text:
            return None

        metadata = trafilatura.extract_metadata(html)

        return ExtractedPage(
            title=metadata.title if metadata else None,
            text=text,
        )

    def _download_html(self, url: str) -> str | None:
        """Download an HTML page from a public address, or return None."""

        headers = {
            "User-Agent": "AI-News-Intelligence/0.2",
            "Accept": "text/html,application/xhtml+xml",
        }

        try:
            # Every redirect hop is resolved and checked again inside the client.
            with make_client(self.timeout_seconds, self.transport) as client:
                response = open_stream(client, url, headers, self.max_redirects)
                with closing(response):
                    response.raise_for_status()

                    if "html" not in response.headers.get("content-type", "").lower():
                        return None

                    body = read_limited(response, self.max_download_bytes)
                    return body.decode(response.encoding or "utf-8", errors="replace")

        except (
            httpx.HTTPError,
            UnicodeError,
            ValueError,
            OSError,
            LookupError,
        ):
            return None

    @staticmethod
    def clean_rss_content(content: str) -> str:
        """Clean HTML contained directly inside an RSS entry."""

        if not content:
            return ""

        extracted = trafilatura.extract(
            content,
            include_comments=False,
            include_tables=False,
            include_links=False,
            favor_precision=True,
            output_format="txt",
        )

        if extracted:
            return extracted.strip()

        # Fallback for very short RSS fragments.
        without_tags = re.sub(r"<[^>]+>", " ", content)
        return re.sub(r"\s+", " ", without_tags).strip()