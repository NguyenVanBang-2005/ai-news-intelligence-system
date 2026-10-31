"""Keyword scoring and rank fusion for public search (POST /ai/search).

Pure functions, no model and no database: the service passes in texts and scores.
Short queries like "google" score low with embeddings alone, so search also ranks
articles by the query words they contain and fuses both rankings.
"""

import math
import re

# Common English words that say nothing about the topic of an article.
STOPWORDS = frozenset({
    "a", "about", "after", "all", "also", "an", "and", "any", "are", "as", "at", "be",
    "been", "but", "by", "can", "do", "does", "for", "from", "has", "have", "how", "if",
    "in", "into", "is", "it", "its", "more", "new", "not", "of", "on", "or", "our", "out",
    "over", "than", "that", "the", "their", "them", "then", "there", "these", "they",
    "this", "to", "up", "was", "we", "were", "what", "when", "where", "which", "who",
    "why", "will", "with", "you", "your",
})

# A query word found in the title counts this many times more than one in the text.
TITLE_WEIGHT = 3.0
CONTENT_WEIGHT = 1.0
# Only the start of the article text is searched for keywords.
KEYWORD_CONTENT_CHARS = 1500
# An article must contain at least this share of the distinct query words to match.
MIN_TERM_COVERAGE = 0.5
# Reciprocal rank fusion constant (the usual value from the original paper).
RRF_K = 60

_WORD = re.compile(r"[^\W_]+")  # runs of letters or digits, any language


def tokenize(text: str) -> list[str]:
    """Lowercase words of letters and digits, without stopwords and one-letter words."""

    return [
        word for word in _WORD.findall(text.lower())
        if len(word) > 1 and word not in STOPWORDS
    ]


def term_weights(query_terms: list[str], documents: list[set[str]]) -> dict[str, float]:
    """An idf weight log(N / df) for each query term found in at least one document.

    Rare words weigh more; a word found in every document weighs 0.
    """

    weights = {}

    for term in set(query_terms):
        document_count = sum(term in words for words in documents)
        if document_count:
            weights[term] = math.log(len(documents) / document_count)

    return weights


def keyword_score(
    weights: dict[str, float], title_words: set[str], content_words: set[str]
) -> float:
    """Sum of the weights of the query terms in an article; title matches count more."""

    score = 0.0

    for term, weight in weights.items():
        if term in title_words:
            score += weight * TITLE_WEIGHT
        elif term in content_words:
            score += weight * CONTENT_WEIGHT

    return score


def term_coverage(query_terms: set[str], words: set[str]) -> float:
    """Share of the query terms found in words (0 when the query has no terms)."""

    return len(query_terms & words) / len(query_terms) if query_terms else 0.0


def keyword_scores(query: str, titles: list[str], contents: list[str]) -> list[float]:
    """Keyword score per article for the query words.

    Only the first KEYWORD_CONTENT_CHARS characters of each content are read. An article
    holding fewer than MIN_TERM_COVERAGE of the query terms scores 0, so one common
    word in a nonsense query ("xyzzy banana quantum") does not match.
    """

    terms = set(tokenize(query))
    title_sets = [set(tokenize(title)) for title in titles]
    content_sets = [set(tokenize(content[:KEYWORD_CONTENT_CHARS])) for content in contents]
    documents = [t | c for t, c in zip(title_sets, content_sets, strict=True)]
    weights = term_weights(list(terms), documents)

    return [
        keyword_score(weights, title, content)
        if term_coverage(terms, words) >= MIN_TERM_COVERAGE else 0.0
        for title, content, words in zip(title_sets, content_sets, documents, strict=True)
    ]


def ranking(scores: list[float]) -> list[int]:
    """Indexes of the positive scores, best first (ties keep their original order)."""

    positive = [index for index, score in enumerate(scores) if score > 0]
    return sorted(positive, key=lambda index: -scores[index])


def reciprocal_rank_fusion(rankings: list[list[int]], k: int = RRF_K) -> dict[int, float]:
    """Fused score per index: the sum of 1 / (k + rank) over the rankings it appears in."""

    fused: dict[int, float] = {}

    for ranked in rankings:
        for rank, index in enumerate(ranked, start=1):
            fused[index] = fused.get(index, 0.0) + 1.0 / (k + rank)

    return fused


def hybrid_order(
    similarities: list[float],
    semantic_scores: list[float],
    keyword_scores: list[float],
    min_similarity: float,
) -> list[int]:
    """Indexes of the articles to show, best first.

    An article is shown when its similarity reaches min_similarity or it contains a
    query word with a positive weight. Both rankings are fused with RRF.
    """

    semantic_ranking = sorted(range(len(semantic_scores)), key=lambda i: -semantic_scores[i])
    fused = reciprocal_rank_fusion([semantic_ranking, ranking(keyword_scores)])
    shown = [
        index for index in range(len(similarities))
        if similarities[index] >= min_similarity or keyword_scores[index] > 0
    ]

    return sorted(shown, key=lambda index: -fused[index])
