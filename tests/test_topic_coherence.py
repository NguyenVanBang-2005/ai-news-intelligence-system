"""NPMI topic coherence: topics whose words appear together score higher."""

import pytest

from app.services.topic_coherence import npmi_coherence

DOCUMENTS = [
    "senate vote bill law",
    "senate vote budget law",
    "senate vote election law",
    "goal match league coach",
    "goal match league referee",
    "goal match league coach",
]


def test_words_that_always_appear_together_score_one() -> None:
    assert npmi_coherence([["senate", "vote", "law"]], DOCUMENTS[:3]) == 1.0


def test_words_that_never_appear_together_score_minus_one() -> None:
    assert npmi_coherence([["senate", "goal"]], DOCUMENTS) == -1.0


def test_a_coherent_topic_beats_a_mixed_topic() -> None:
    coherent = npmi_coherence([["senate", "vote", "law"], ["goal", "match", "league"]], DOCUMENTS)
    mixed = npmi_coherence([["senate", "goal", "law"], ["vote", "match", "league"]], DOCUMENTS)

    assert coherent > mixed


def test_words_are_matched_as_whole_words_in_any_case() -> None:
    assert npmi_coherence([["art", "party"]], ["Party time", "department party"]) == -1.0
    assert npmi_coherence([["party", "time"]], ["Party TIME", "party time"]) == 1.0


@pytest.mark.parametrize("topic_words", [[], [["single"]], [[]]])
def test_nothing_to_measure_is_none(topic_words: list[list[str]]) -> None:
    assert npmi_coherence(topic_words, DOCUMENTS) is None
