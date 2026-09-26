import re
from urllib.parse import urljoin

import httpx
import trafilatura

from app.services.feed import validate_public_url


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

                    return trafilatura.extract(
                        response.text,
                        include_comments=False,
                        include_tables=False,
                        include_links=False,
                        favor_precision=True,
                        output_format="txt",
                    )

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