"""News search: find articles for a request or a link, summarize each, answer with citations."""

import logging
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlparse

import numpy as np
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.article import Article
from app.repositories.article import ArticleRepository
from app.repositories.source import SourceRepository
from app.services.ai_errors import EmbeddingModelUnavailableError
from app.services.analyzer import HeuristicAnalyzer
from app.services.content_extractor import ArticleContentExtractor
from app.services.embeddings import ArticleEmbedder, encode_queries, get_embedding_model
from app.services.llm import LLMClient, LLMError
from app.services.prompts import (
    ANSWER_SYSTEM,
    SUMMARY_SYSTEM,
    answer_prompt,
    summary_prompt,
)
from app.services.text_cleaning import truncate

logger = logging.getLogger(__name__)

SUMMARY_AI = "ai"
SUMMARY_CACHED = "cached"
SUMMARY_EXTRACTIVE = "extractive"

LINK_NOT_ALLOWED_MESSAGE = (
    "Reading a link requires admin access. Please enter search keywords instead."
)

LINK_INPUT_DISABLED_MESSAGE = "Link input is disabled (ASK_ALLOW_LINKS=false)."

# News goes stale: a fresh article gets up to this much added to its ranking
# score, fading over about a week. Similarity still decides what is relevant.
RECENCY_WEIGHT = 0.05
RECENCY_DECAY_DAYS = 7


class LinkUnreadableError(ValueError):
    pass


class LinkNotAllowedError(ValueError):
    """Public search only looks in stored articles; reading a link needs /ai/ask."""


class LinkInputDisabledError(ValueError):
    """/ai/ask got a link while ASK_ALLOW_LINKS is false."""


@dataclass(frozen=True)
class FoundSource:
    article: Article
    similarity: float
    summary: str
    summary_method: str


@dataclass(frozen=True)
class SearchAnswer:
    answer: str | None
    sources: list[FoundSource]


def is_link(text: str) -> bool:
    parsed = urlparse(text)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc) and " " not in text


# Host name: dot-separated labels ending in an alphabetic TLD, then an optional port,
# path, query or fragment.
_DOMAIN = re.compile(
    r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+(?P<tld>[a-z]{2,63})"
    r"(?P<rest>(?::\d{1,5})?(?:[/?#]\S*)?)",
    re.IGNORECASE,
)

# TLDs that make a bare "name.tld" a link. Purely syntactic matching would also catch search
# words like "node.js" or "vue.js", so a bare name needs one of these; a path, port, query or
# a "www." prefix is enough on its own. File-extension-like ccTLDs (.js .py .md .rs .sh .ts)
# are deliberately absent.
COMMON_TLDS = frozenset({
    "com", "net", "org", "edu", "gov", "int", "mil", "info", "biz", "io", "ai", "co", "app",
    "dev", "news", "tech", "online", "site", "blog", "xyz", "me", "tv",
    "us", "uk", "eu", "de", "fr", "es", "it", "nl", "se", "no", "ch", "pl", "ru", "cn",
    "jp", "kr", "in", "au", "ca", "br", "vn",
})


def looks_like_link(text: str) -> bool:
    """Whether a public search input is a link (refused there) rather than search words.

    Stricter than is_link, which /ai/ask keeps using for its link flow. Links:
    anything starting with http:// or https://, and, without whitespace, a host name that has
    a path/port/query, starts with "www." or ends in a common TLD ("example.com/a",
    "www.example.com", "example.com"). Search words: anything with whitespace ("AI
    regulation"), no dot ("gpt-5"), a non-alphabetic or one-letter last part ("v1.2",
    "e.g."), or a bare name with an uncommon TLD ("node.js").
    A missed link is harmless: search never downloads, it only searches the words.
    """

    text = text.strip()

    if text.lower().startswith(("http://", "https://")):
        return True

    if any(character.isspace() for character in text):
        return False

    match = _DOMAIN.fullmatch(text)

    if match is None:
        return False

    return (
        bool(match["rest"])
        or text.lower().startswith("www.")
        or match["tld"].lower() in COMMON_TLDS
    )


class NewsSearchService:
    def __init__(
        self,
        db: Session,
        *,
        llm: LLMClient | None = None,
        extractor: ArticleContentExtractor | None = None,
    ):
        self.articles = ArticleRepository(db)
        self.sources = SourceRepository(db)
        # Created on first use, so search() never builds a client that reaches outside.
        self._llm = llm
        self._extractor = extractor
        self.analyzer = HeuristicAnalyzer()
        # Set to False after the first failed LLM call, so one request never
        # waits for the same timeout once per source.
        self.llm_available = True

    @property
    def llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = LLMClient.from_settings()
        return self._llm

    @property
    def extractor(self) -> ArticleContentExtractor:
        if self._extractor is None:
            self._extractor = ArticleContentExtractor(
                timeout_seconds=settings.request_timeout_seconds,
                max_download_bytes=settings.article_max_download_bytes,
                max_redirects=settings.article_max_redirects,
            )
        return self._extractor

    def search(self, text: str) -> list[FoundSource]:
        """Stored articles matching a search request, with extractive summaries.

        Offline by design: no link download, no LLM call, nothing leaves the server.
        """

        text = text.strip()

        if looks_like_link(text):
            raise LinkNotAllowedError(LINK_NOT_ALLOWED_MESSAGE)

        model, embedder = self._embedding()
        # Only the query is encoded; articles without a stored embedding are skipped
        # (POST /ai/process computes them).
        matches = self._related_articles(
            encode_queries(model, [text])[0],
            embedder,
            exclude_ids=set(),
            count=settings.ask_max_sources,
            cached_only=True,
        )

        return [
            FoundSource(article, similarity, article.ai_summary, SUMMARY_CACHED)
            if article.ai_summary
            else FoundSource(
                article, similarity, self._extractive_summary(article), SUMMARY_EXTRACTIVE
            )
            for article, similarity in matches
        ]

    def ask(self, request: str) -> SearchAnswer:
        """Answer a search request, or explain a link, using the stored articles."""

        request = request.strip()

        # Checked first: loading the embedding model and reading the link may both use the network.
        if is_link(request) and not settings.ask_allow_links:
            raise LinkInputDisabledError(LINK_INPUT_DISABLED_MESSAGE)

        model, embedder = self._embedding()

        if is_link(request):
            linked_article = self._article_for_link(request)
            query_embedding = embedder.embed([linked_article])[0]
            matches = [(linked_article, 1.0)]
            question = (
                "What is this article about, and what does related coverage add? "
                f"Article: {linked_article.title}"
            )
        else:
            query_embedding = encode_queries(model, [request])[0]
            matches = []
            question = request

        matches += self._related_articles(
            query_embedding,
            embedder,
            exclude_ids={article.id for article, _ in matches},
            count=settings.ask_max_sources - len(matches),
        )

        sources = [
            self._with_summary(article, similarity)
            for article, similarity in matches
        ]

        return SearchAnswer(
            answer=self._answer(question, sources),
            sources=sources,
        )

    def _embedding(self) -> tuple[object, ArticleEmbedder]:
        try:
            model = get_embedding_model()
        except OSError as exc:
            raise EmbeddingModelUnavailableError from exc

        return model, ArticleEmbedder(self.articles, model)

    def _article_for_link(self, url: str) -> Article:
        """The stored article for this URL, downloading and saving it when needed."""

        existing = self.articles.get_by_url(url)

        if existing and existing.content:
            return existing

        page = self.extractor.extract_page(url)

        if page is None:
            raise LinkUnreadableError(
                "The link could not be read. Check that it is a public news article."
            )

        content = truncate(page.text, settings.max_article_content_chars)

        if existing:  # known from RSS, but without its text until now
            self.articles.save_content(existing, content)
            return existing

        title = (page.title or url)[:500]
        analysis = self.analyzer.analyze(title, content)

        return self.articles.create(
            source_id=self.sources.get_or_create_user_links().id,
            title=title,
            url=url,
            content=content,
            summary=analysis.summary,
            topic=analysis.topic,
            confidence=analysis.confidence,
            status="analyzed",
        )

    def _related_articles(
        self,
        query_embedding: np.ndarray,
        embedder: ArticleEmbedder,
        *,
        exclude_ids: set[int],
        count: int,
        cached_only: bool = False,
    ) -> list[tuple[Article, float]]:
        """The best matching articles with their similarity, one per story.

        cached_only: compare only with stored embeddings, never encode articles.
        """

        candidates = [
            article
            for article in self.articles.list_for_search(
                limit=settings.ask_max_candidates, only_embedded=cached_only
            )
            if article.id not in exclude_ids
        ]

        if not candidates or count <= 0:
            return []

        if cached_only:
            candidates, embeddings = embedder.cached(candidates)
            if not candidates:
                return []
        else:
            embeddings = embedder.embed(candidates)
        similarities = embeddings @ query_embedding
        scores = similarities + np.array(
            [self._recency_boost(article) for article in candidates]
        )

        picked: list[int] = []
        # The linked article itself counts as found, so copies of it are skipped too.
        found_embeddings = [query_embedding] if exclude_ids else []

        for index in np.argsort(-scores):
            if similarities[index] < settings.ask_min_similarity:
                continue

            if any(
                float(found @ embeddings[index]) >= settings.duplicate_similarity_threshold
                for found in found_embeddings
            ):
                continue  # the same story from another outlet

            picked.append(int(index))
            found_embeddings.append(embeddings[index])

            if len(picked) == count:
                break

        return [(candidates[index], float(similarities[index])) for index in picked]

    @staticmethod
    def _recency_boost(article: Article) -> float:
        date = article.published_at or article.created_at

        if date is None:
            return 0.0

        age_days = max(0.0, (datetime.now(UTC) - date).total_seconds() / 86_400)

        return RECENCY_WEIGHT * math.exp(-age_days / RECENCY_DECAY_DAYS)

    def _with_summary(self, article: Article, similarity: float) -> FoundSource:
        if article.ai_summary:
            return FoundSource(article, similarity, article.ai_summary, SUMMARY_AI)

        summary = self._ask_llm(SUMMARY_SYSTEM, summary_prompt(article))

        if summary:
            self.articles.save_ai_summary(article, summary)
            return FoundSource(article, similarity, summary, SUMMARY_AI)

        # The LLM is unavailable: fall back to the first sentences of the article.
        return FoundSource(
            article, similarity, self._extractive_summary(article), SUMMARY_EXTRACTIVE
        )

    def _extractive_summary(self, article: Article) -> str:
        return article.summary or self.analyzer.analyze(article.title, article.content).summary

    def _answer(self, question: str, sources: list[FoundSource]) -> str | None:
        if not sources:
            return None

        return self._ask_llm(
            ANSWER_SYSTEM,
            answer_prompt(question, [(source.article, source.summary) for source in sources]),
        )

    def _ask_llm(self, system: str, user: str) -> str | None:
        """The model's reply, or None when the model is unavailable."""

        if not self.llm_available:
            return None

        try:
            return self.llm.complete(system=system, user=user)
        except LLMError:
            logger.warning("LLM unavailable, using extractive summaries", exc_info=True)
            self.llm_available = False
            return None
