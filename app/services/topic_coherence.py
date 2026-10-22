import re
from itertools import combinations

import numpy as np


def npmi_coherence(
    topic_words: list[list[str]],
    documents: list[str],
) -> float | None:
    """
    Average NPMI of the top words of each topic, from -1 (words never appear
    together) to 1 (always appear together). Returns None when there is
    nothing to measure.

    Words co-occur when they are in the same document. Higher is better, so
    compare the value between batches to see whether a tuning change helped.
    """

    topic_scores = [
        score
        for words in topic_words
        if (score := _topic_npmi(words, documents)) is not None
    ]

    if not topic_scores:
        return None

    return round(float(np.mean(topic_scores)), 4)


def _topic_npmi(words: list[str], documents: list[str]) -> float | None:
    lowered_documents = [document.lower() for document in documents]
    presence = {
        word: np.array([_contains_word(document, word) for document in lowered_documents])
        for word in words
    }

    pair_scores = [
        _npmi(presence[first], presence[second])
        for first, second in combinations(words, 2)
    ]

    if not pair_scores:
        return None

    return float(np.mean(pair_scores))


def _contains_word(document: str, word: str) -> bool:
    return re.search(rf"\b{re.escape(word.lower())}\b", document) is not None


def _npmi(first: np.ndarray, second: np.ndarray) -> float:
    total = len(first)
    p_first = first.sum() / total
    p_second = second.sum() / total
    p_both = (first & second).sum() / total

    if p_both == 0:
        return -1.0

    if p_both == 1:
        return 1.0

    pmi = np.log(p_both / (p_first * p_second))

    return float(pmi / -np.log(p_both))
