"""Pure keyword scoring and rank fusion used by POST /ai/search (no model, no database)."""

import math

import pytest

from app.services.hybrid_search import (
    KEYWORD_CONTENT_CHARS,
    RRF_K,
    hybrid_order,
    keyword_score,
    keyword_scores,
    ranking,
    reciprocal_rank_fusion,
    term_coverage,
    term_weights,
    tokenize,
)

# --- tokenize ------------------------------------------------------------------------------


def test_tokenize_lowercases_and_drops_punctuation() -> None:
    assert tokenize("Google's AI-news, GPT-5!") == ["google", "ai", "news", "gpt"]


def test_tokenize_drops_stopwords_and_one_letter_words() -> None:
    assert tokenize("AI agents in the enterprise, a B c") == ["ai", "agents", "enterprise"]


def test_tokenize_keeps_digits_and_non_english_letters() -> None:
    assert tokenize("Tin tức AI 2026") == ["tin", "tức", "ai", "2026"]


@pytest.mark.parametrize("text", ["", "the of and", "!!! ---"])
def test_tokenize_can_be_empty(text: str) -> None:
    assert tokenize(text) == []


# --- weights and scores --------------------------------------------------------------------


def test_rare_word_weighs_more_than_common_word() -> None:
    documents = [{"ai", "google"}, {"ai"}, {"ai"}, {"ai", "chips"}]

    weights = term_weights(["ai", "google"], documents)

    assert weights["google"] == pytest.approx(math.log(4 / 1))
    assert weights["ai"] == 0.0  # in every document
    assert weights["google"] > weights["ai"]


def test_unknown_word_has_no_weight() -> None:
    assert term_weights(["xyzzy"], [{"ai"}, {"google"}]) == {}


def test_title_match_scores_more_than_content_match() -> None:
    weights = {"google": 2.0}

    in_title = keyword_score(weights, {"google"}, set())
    in_content = keyword_score(weights, set(), {"google"})

    assert in_title > in_content > 0
    assert keyword_score(weights, set(), {"microsoft"}) == 0


def test_term_coverage() -> None:
    assert term_coverage({"binance", "hack"}, {"hack", "crypto"}) == 0.5
    assert term_coverage(set(), {"anything"}) == 0.0


def test_keyword_scores_need_half_of_the_query_words() -> None:
    titles = ["Quantum chips", "Google news", "Weather", "Sports"]
    contents = ["", "", "", ""]

    # One word out of three: not a match.
    assert keyword_scores("xyzzy banana quantum", titles, contents) == [0.0] * 4
    # One word out of one: a match.
    assert keyword_scores("quantum", titles, contents)[0] > 0


def test_keyword_scores_read_only_the_start_of_the_content() -> None:
    late = "filler " * KEYWORD_CONTENT_CHARS + "google"

    scores = keyword_scores("google", ["One", "Two", "Three"], ["google early", late, ""])

    assert scores[0] > 0
    assert scores[1] == 0.0


# --- ranking and fusion --------------------------------------------------------------------


def test_ranking_keeps_positive_scores_best_first() -> None:
    assert ranking([0.0, 2.0, 1.0, 2.0, -1.0]) == [1, 3, 2]


def test_reciprocal_rank_fusion_adds_both_rankings() -> None:
    fused = reciprocal_rank_fusion([[0, 1], [1]])

    assert fused[0] == pytest.approx(1 / (RRF_K + 1))
    assert fused[1] == pytest.approx(1 / (RRF_K + 2) + 1 / (RRF_K + 1))
    assert fused[1] > fused[0]  # found by both beats first in only one


def test_hybrid_order_keeps_keyword_matches_below_the_floor() -> None:
    similarities = [0.9, 0.2, 0.1]
    keyword = [0.0, 0.0, 3.0]

    order = hybrid_order(similarities, similarities, keyword, min_similarity=0.5)

    assert sorted(order) == [0, 2]  # 1 has neither enough similarity nor a keyword


def test_hybrid_order_is_empty_without_similarity_or_keywords() -> None:
    assert hybrid_order([0.3, 0.2], [0.3, 0.2], [0.0, 0.0], min_similarity=0.5) == []


def test_hybrid_order_puts_an_article_found_both_ways_first() -> None:
    similarities = [0.9, 0.8, 0.7]
    keyword = [0.0, 0.0, 5.0]

    order = hybrid_order(similarities, similarities, keyword, min_similarity=0.5)

    # 2 is third by meaning but first by keyword: 1/63 + 1/61 beats 1/61 alone.
    assert order == [2, 0, 1]
