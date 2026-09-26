from app.services.analyzer import HeuristicAnalyzer


def test_analyzer_detects_generative_ai() -> None:
    result = HeuristicAnalyzer().analyze(
        "A new GPT model is released", "The language model improves transformer efficiency."
    )

    assert result.topic == "Generative AI"
    assert result.confidence > 0.5
    assert result.summary


def test_analyzer_uses_other_when_no_keyword_matches() -> None:
    result = HeuristicAnalyzer().analyze("A quiet day", "Nothing unusual happened.")

    assert result.topic == "Other"
    assert result.confidence == 0.3

