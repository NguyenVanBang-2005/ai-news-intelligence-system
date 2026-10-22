import re
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx
import trafilatura

from app.services.feed import validate_public_url


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
    ):
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

        current_url = url

        try:
            with httpx.Client(
                timeout=self.timeout_seconds,
                follow_redirects=False,
            ) as client:
                for _ in range(self.max_redirects + 1):
                    # Recheck every redirect target to reduce SSRF risk.
                    validate_public_url(current_url)

                    response = client.get(
                        current_url,
                        headers={
                            "User-Agent": "AI-News-Intelligence/0.2",
                            "Accept": "text/html,application/xhtml+xml",
                        },
                    )

                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            return None

                        current_url = urljoin(current_url, location)
                        continue

                    response.raise_for_status()

                    content_type = response.headers.get(
                        "content-type",
                        "",
                    ).lower()

                    if "html" not in content_type:
                        return None

                    if len(response.content) > self.max_download_bytes:
                        return None

                    return response.text

        except (
            httpx.HTTPError,
            UnicodeError,
            ValueError,
            OSError,
        ):
            return None

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