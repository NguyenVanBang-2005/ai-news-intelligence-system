"""ASK_ALLOW_LINKS: with the flag off, POST /ai/ask refuses links before any network use.

MOCK NOTICE: the embedding model, page extractor and LLM are the stand-ins of
test_news_search. With links disabled they are swapped for blockers that record every call,
and real HTTP transports are blocked too, so the tests prove nothing reached outside.
"""

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

try:
    import app.services.news_search as news_search
except (ImportError, OSError) as exc:  # optional ML stack missing or blocked by the OS
    pytest.skip(f"AI dependencies unavailable: {exc}", allow_module_level=True)

from app.services.content_extractor import ExtractedPage
from app.services.llm import LLMClient
from tests.test_news_search import FakeEmbedder, FakeExtractor, FakeLLM, seed

LINK = "https://elsewhere.example/g1-story"
DISABLED_MESSAGE = "Link input is disabled (ASK_ALLOW_LINKS=false)."


@pytest.fixture(autouse=True)
def offline_fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fake model, extractor and LLM, as in test_news_search; links allowed by default."""
    llm_client = LLMClient(base_url="http://llm.test/v1", model="test-model", api_key="key",
                           timeout_seconds=5, transport=httpx.MockTransport(FakeLLM().handle))
    monkeypatch.setattr(news_search, "get_embedding_model", lambda: FakeEmbedder())
    monkeypatch.setattr(news_search.LLMClient, "from_settings", classmethod(lambda cls: llm_client))
    monkeypatch.setattr(news_search, "ArticleContentExtractor", FakeExtractor)
    monkeypatch.setattr(news_search.settings, "ask_min_similarity", 0.5)
    monkeypatch.setattr(news_search.settings, "ask_allow_links", True)
    FakeExtractor.pages, FakeExtractor.calls = {}, []


@pytest.fixture
def links_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(news_search.settings, "ask_allow_links", False)


@pytest.fixture
def network_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace everything that can reach the network with blockers; returns what was called."""
    calls: list[str] = []

    def blocker(name: str):
        def blocked(*args: object, **kwargs: object):
            calls.append(name)
            raise AssertionError(f"{name} must not be called while links are disabled")
        return blocked

    monkeypatch.setattr(news_search, "get_embedding_model", blocker("embedding model"))
    monkeypatch.setattr(news_search, "ArticleContentExtractor", blocker("page extractor"))
    monkeypatch.setattr(news_search.LLMClient, "from_settings", classmethod(blocker("LLM")))
    # Real HTTP only; the TestClient uses its own in-process transport.
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", blocker("httpx"))
    return calls


def ask(client: TestClient, text: str) -> httpx.Response:
    return client.post("/api/v1/ai/ask", json={"input": text})


@pytest.mark.usefixtures("links_disabled")
def test_a_link_is_refused_with_422_before_any_network_call(
    client: TestClient, engine: Engine, network_calls: list[str]
) -> None:
    seed(engine)

    response = ask(client, LINK)

    assert response.status_code == 422
    assert response.json()["detail"] == DISABLED_MESSAGE
    assert network_calls == []


def test_a_link_is_downloaded_as_before_when_allowed(client: TestClient, engine: Engine) -> None:
    seed(engine)
    FakeExtractor.pages[LINK] = ExtractedPage(title="Big G1 news", text="G1 full article text.")

    response = ask(client, LINK)

    assert response.status_code == 200
    assert response.json()["sources"][0]["url"] == LINK
    assert FakeExtractor.calls == [LINK]


@pytest.mark.parametrize("allow_links", [True, False])
def test_search_words_are_not_affected_by_the_flag(
    client: TestClient, engine: Engine, monkeypatch: pytest.MonkeyPatch, allow_links: bool
) -> None:
    ids = seed(engine)
    monkeypatch.setattr(news_search.settings, "ask_allow_links", allow_links)

    response = ask(client, "latest on G0")

    assert response.status_code == 200
    assert {source["id"] for source in response.json()["sources"]} <= set(ids[0])
    assert response.json()["sources"]


@pytest.mark.usefixtures("links_disabled")
def test_public_search_keeps_its_own_link_message(client: TestClient) -> None:
    response = client.post("/api/v1/ai/search", json={"input": LINK})

    assert response.status_code == 422
    assert response.json()["detail"] == news_search.LINK_NOT_ALLOWED_MESSAGE
