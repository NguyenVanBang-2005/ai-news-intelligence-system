import re
from dataclasses import dataclass


@dataclass(frozen=True)
class AnalysisResult:
    summary: str
    topic: str
    confidence: float


class HeuristicAnalyzer:
    """Deterministic baseline that can later be replaced by an ML implementation."""

    TOPIC_KEYWORDS = {
        "Generative AI": {"llm", "gpt", "generative", "language model", "chatbot", "transformer"},
        "Computer Vision": {"vision", "image", "video", "diffusion", "object detection"},
        "Robotics": {"robot", "robotics", "autonomous", "humanoid"},
        "AI Research": {"research", "paper", "benchmark", "dataset", "arxiv"},
        "AI Business": {"funding", "startup", "revenue", "acquisition", "enterprise"},
        "AI Policy": {"regulation", "policy", "law", "safety", "copyright", "government"},
    }

    def analyze(self, title: str, content: str) -> AnalysisResult:
        text = f"{title}. {content}".strip()
        lowered = text.lower()
        scores = {
            topic: sum(1 for keyword in keywords if keyword in lowered)
            for topic, keywords in self.TOPIC_KEYWORDS.items()
        }
        topic, score = max(scores.items(), key=lambda item: item[1])
        if score == 0:
            topic = "Other"
        confidence = min(0.95, 0.45 + score * 0.1) if score else 0.3
        return AnalysisResult(
            summary=self._summarize(text), topic=topic, confidence=round(confidence, 2)
        )

    @staticmethod
    def _summarize(text: str, max_sentences: int = 2, max_chars: int = 500) -> str:
        clean = re.sub(r"\s+", " ", text).strip()
        sentences = re.split(r"(?<=[.!?])\s+", clean)
        summary = " ".join(sentences[:max_sentences])
        if len(summary) <= max_chars:
            return summary
        return summary[: max_chars - 1].rsplit(" ", 1)[0] + "…"

