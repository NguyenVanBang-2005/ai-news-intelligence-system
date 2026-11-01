"""POST /api/v1/ai/search: public, offline search in the stored articles.

MOCK NOTICE: the sentence-transformer is the `FakeEmbedder` of test_news_search. The LLM
client and the content extractor are replaced by stand-ins that fail the test if they are
ever created, so these tests also prove that search never reaches outside. Article
embeddings are stored up front, as POST /ai/process would.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

try:
    import app.services.news_search as news_search
except (ImportError, OSError) as exc:  # optional ML stack missing or blocked by the OS
    pytest.skip(f"AI dependencies unavailable: {exc}", allow_module_level=True)

import app.services.embeddings as embeddings
from app.api.deps import search_rate_limiter
from app.core.body_limit import BodySizeLimitMiddleware
from app.models.article import Article
from app.repositories.article import ArticleRepository
from tests.test_news_search import FakeEmbedder, seed

LINK_MESSAGE = "Reading a link requires admin access. Please enter search keywords instead."


class ForbiddenLLM:
    def __init__(self, *args: object, **kwargs: object) -> None:
        pytest.fail("search must not create an LLM client")

    @classmethod
    def from_settings(cls) -> None:
        pytest.fail("search must not create an LLM client")


class ForbiddenExtractor:
    def __init__(self, *args: object, **kwargs: object) -> None:
        pytest.fail("search must not create a content extractor")


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(news_search, "get_embedding_model", lambda: FakeEmbedder())
    monkeypatch.setattr(news_search, "LLMClient", ForbiddenLLM)
    monkeypatch.setattr(news_search, "ArticleContentExtractor", ForbiddenExtractor)
    monkeypatch.setattr(news_search.settings, "ask_min_similarity", 0.5)


@pytest.fixture
def anonymous(client: TestClient) -> TestClient:
    """The shared client without its default admin header."""
    client.headers.pop("X-Admin-Token", None)
    return client


def embed_stored(engine: Engine, *, groups: set[int] | None = None) -> None:
    """Store embeddings like POST /ai/process does; only for `groups` when given."""
    with Session(engine) as db:
        articles = [
            article for article in db.scalars(select(Article))
            if groups is None or any(f"G{group} " in article.title for group in groups)
        ]
        embeddings.ArticleEmbedder(ArticleRepository(db), FakeEmbedder()).embed(articles)
        db.commit()


def search(client: TestClient, text: str):
    return client.post("/api/v1/ai/search", json={"input": text})


# --- public access and results ----------------------------------------------------------


def test_search_is_public_and_finds_stored_articles(
    anonymous: TestClient, engine: Engine
) -> None:
    ids = seed(engine)
    embed_stored(engine)

    response = search(anonymous, "news about G1")

    assert response.status_code == 200, response.text
    sources = response.json()["sources"]
    assert sources and sources[0]["id"] in ids[1]


def test_results_have_no_answer_and_at_most_max_sources(
    anonymous: TestClient, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(news_search.settings, "ask_max_sources", 2)
    # Keep every article of the group: only the source limit may cut the list.
    monkeypatch.setattr(news_search.settings, "duplicate_similarity_threshold", 1.01)
    seed(engine, groups=(0,), per_group=5)
    embed_stored(engine)

    body = search(anonymous, "G0 latest").json()

    assert "answer" not in body
    assert len(body["sources"]) == 2


def test_results_carry_the_article_topic(anonymous: TestClient, engine: Engine) -> None:
    ids = seed(engine, groups=(0,))
    embed_stored(engine)
    labelled_id = ids[0][0]
    with Session(engine) as db:
        db.get(Article, labelled_id).topic = "AI Policy"
        db.commit()

    sources = search(anonymous, "G0 latest").json()["sources"]

    by_id = {source["id"]: source["topic"] for source in sources}
    assert by_id[labelled_id] == "AI Policy"
    # Unlabelled articles report null rather than dropping the field.
    assert [topic for article_id, topic in by_id.items() if article_id != labelled_id] == [
        None
    ] * (len(by_id) - 1)


# --- summaries --------------------------------------------------------------------------


def test_summaries_are_extractive_without_a_stored_ai_summary(
    anonymous: TestClient, engine: Engine
) -> None:
    seed(engine)
    embed_stored(engine)

    sources = search(anonymous, "G0 latest").json()["sources"]

    assert sources
    assert {source["summary_method"] for source in sources} == {"extractive"}
    assert all(source["summary"].startswith("Excerpt G0") for source in sources)


def test_a_stored_ai_summary_is_reused_as_cached(anonymous: TestClient, engine: Engine) -> None:
    ids = seed(engine)
    embed_stored(engine)
    summarized_id = ids[0][0]
    with Session(engine) as db:
        db.get(Article, summarized_id).ai_summary = "Stored LLM summary."
        db.commit()

    sources = search(anonymous, "G0 latest").json()["sources"]

    by_id = {source["id"]: source for source in sources}
    assert by_id[summarized_id]["summary"] == "Stored LLM summary."
    assert by_id[summarized_id]["summary_method"] == "cached"
    others = [source for source in sources if source["id"] != summarized_id]
    assert others and {source["summary_method"] for source in others} == {"extractive"}
    # ForbiddenLLM would have failed the test if a client had been created.


# --- no article embedding ------------------------------------------------------------------


def test_articles_without_stored_embedding_are_skipped_not_embedded(
    anonymous: TestClient, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = seed(engine)
    embed_stored(engine, groups={0})  # group 1 was never processed

    def no_article_encoding(*args: object, **kwargs: object) -> None:
        pytest.fail("search must not embed articles")

    monkeypatch.setattr(embeddings, "encode_passages", no_article_encoding)
    monkeypatch.setattr(embeddings.ArticleEmbedder, "embed", no_article_encoding)

    g1 = search(anonymous, "G1 latest")
    g0 = search(anonymous, "G0 latest")

    assert g1.status_code == g0.status_code == 200
    assert not {source["id"] for source in g1.json()["sources"]} & set(ids[1])
    assert g0.json()["sources"]
    with Session(engine) as db:
        for article_id in ids[1]:
            assert db.get(Article, article_id).embedding is None


def test_a_stale_embedding_is_skipped(anonymous: TestClient, engine: Engine) -> None:
    ids = seed(engine, groups=(0,), per_group=1)
    embed_stored(engine)
    with Session(engine) as db:  # text changed after /ai/process: embedding no longer valid
        db.get(Article, ids[0][0]).content = "G0 rewritten article text."
        db.commit()

    assert search(anonymous, "G0 latest").json()["sources"] == []


# --- hybrid search: meaning + keywords -------------------------------------------------


def seed_company_news(engine: Engine) -> dict[str, int]:
    """Articles with company names and no 'G<k>' marker, so their embedding similarity
    to a short query is low (FakeEmbedder noise); returns their ids by title."""
    stories = {
        "Google launches a quantum model": "Google said the model runs on its own chips.",
        "Google cuts cloud prices": "The company lowered prices for storage.",
        "Microsoft ships Copilot update": "Copilot gets new agents this week.",
        "Weather turns cold in Hanoi": "Temperatures drop sharply at night.",
    }
    seed(engine, groups=(0,))  # unrelated articles
    with Session(engine) as db:
        source_id = db.scalars(select(Article.source_id)).first()
        for index, (title, content) in enumerate(stories.items()):
            db.add(Article(
                source_id=source_id, title=title, url=f"https://daily.example/c{index}",
                content=content, summary=f"Excerpt {title}.", status="analyzed",
            ))
        db.commit()
        return {a.title: a.id for a in db.scalars(select(Article)) if a.title in stories}


def test_a_short_keyword_finds_articles_with_low_similarity(
    anonymous: TestClient, engine: Engine
) -> None:
    ids = seed_company_news(engine)
    embed_stored(engine)

    sources = search(anonymous, "google").json()["sources"]

    found = {source["id"] for source in sources}
    assert found == {ids["Google launches a quantum model"], ids["Google cuts cloud prices"]}
    # Below the similarity floor: found only through the keyword.
    assert all(
        source["similarity"] < news_search.settings.ai_search_min_similarity
        for source in sources
    )


@pytest.mark.parametrize("text", ["xyzzy banana quantum", "qwertyuiop asdfgh"])
def test_nonsense_words_find_nothing(
    anonymous: TestClient, engine: Engine, text: str
) -> None:
    seed_company_news(engine)
    embed_stored(engine)

    # "quantum" is in one title, but one word out of three is not a match.
    assert search(anonymous, text).json()["sources"] == []


def test_an_exact_title_comes_first(anonymous: TestClient, engine: Engine) -> None:
    ids = seed_company_news(engine)
    embed_stored(engine)

    sources = search(anonymous, "Microsoft ships Copilot update").json()["sources"]

    assert sources[0]["id"] == ids["Microsoft ships Copilot update"]


def test_ask_keeps_its_own_similarity_floor(
    client: TestClient, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_company_news(engine)
    embed_stored(engine)
    monkeypatch.setattr(news_search.settings, "ai_search_min_similarity", 0.0)

    # /ai/ask has no keyword part and ignores AI_SEARCH_MIN_SIMILARITY.
    asked = client.post("/api/v1/ai/ask", json={"input": "google"})

    assert asked.status_code == 200
    assert asked.json()["sources"] == []


# --- link detection -------------------------------------------------------------------


@pytest.mark.parametrize("link", [
    "https://daily.example/0-0",
    "http://example.com/a?b=c",
    "HTTPS://EXAMPLE.COM",
    "example.com/a",
    "www.example.com",
    "example.com",
    "vnexpress.net/tin-tuc",
    "news.example.org:8080",
    "node.js/docs",  # a path makes it a link
])
def test_a_link_is_refused_with_422(
    anonymous: TestClient, monkeypatch: pytest.MonkeyPatch, link: str
) -> None:
    def no_model() -> None:
        pytest.fail("a link must be refused before the model is loaded")

    monkeypatch.setattr(news_search, "get_embedding_model", no_model)

    response = search(anonymous, link)

    assert response.status_code == 422
    assert response.json()["detail"] == LINK_MESSAGE


@pytest.mark.parametrize("text", [
    "gpt-5 release",
    "AI regulation",
    "gpt-5",
    "e.g.",      # last part empty
    "v1.2",      # numeric last part
    "gpt-4.5",
    "node.js",   # "js" is not treated as a TLD
    "vue.js",
    "see example.com",  # whitespace: search words
])
def test_search_words_are_searched(anonymous: TestClient, text: str) -> None:
    assert news_search.looks_like_link(text) is False
    assert search(anonymous, text).status_code == 200


def test_ask_link_detection_is_unchanged() -> None:
    # /ai/ask keeps its own, looser rule: only http(s) URLs are links there.
    assert news_search.is_link("https://example.com/a")
    assert not news_search.is_link("example.com/a")


# --- errors and limits ---------------------------------------------------------------------


def test_missing_embedding_model_is_503(
    anonymous: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unavailable() -> None:
        raise OSError("model files missing")

    monkeypatch.setattr(news_search, "get_embedding_model", unavailable)

    assert search(anonymous, "G0 latest").status_code == 503


@pytest.mark.parametrize("text", ["x", "x" * 501])
def test_input_length_is_limited(anonymous: TestClient, text: str) -> None:
    assert search(anonymous, text).status_code == 422


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_rate_limit_returns_429_then_recovers(
    anonymous: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = FakeClock()
    monkeypatch.setattr(search_rate_limiter, "clock", clock)
    monkeypatch.setattr(news_search.settings, "ai_search_rate_per_minute", 3)

    allowed = [search(anonymous, "G0 latest").status_code for _ in range(3)]
    clock.now += 20
    limited = search(anonymous, "G0 latest")

    assert allowed == [200, 200, 200]
    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) == 40  # until the first hit leaves the window
    assert limited.json()["detail"].startswith("Too many searches")

    clock.now += 41
    assert search(anonymous, "G0 latest").status_code == 200


def test_ask_is_not_rate_limited(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(news_search.settings, "ai_search_rate_per_minute", 1)

    # Admin client; an empty store means /ai/ask never needs the (forbidden) LLM.
    statuses = [
        client.post("/api/v1/ai/ask", json={"input": "G0 latest"}).status_code
        for _ in range(3)
    ]

    assert statuses == [200, 200, 200]


def test_ask_still_needs_the_admin_token(anonymous: TestClient) -> None:
    response = anonymous.post("/api/v1/ai/ask", json={"input": "G0 latest"})

    assert response.status_code == 401


# --- body size -------------------------------------------------------------------------


def test_a_5kb_body_is_refused_before_parsing(anonymous: TestClient) -> None:
    body = b'{"input": "' + b"x" * 5 * 1024 + b'"}'

    response = anonymous.post(
        "/api/v1/ai/search", content=body, headers={"Content-Type": "application/json"}
    )

    # 413, not the schema's 422: the body never reached Pydantic.
    assert response.status_code == 413
    assert response.json()["detail"] == "Request body is too large."


def test_a_small_body_is_accepted(anonymous: TestClient) -> None:
    body = b'{"input": "' + b"G0 " * 28 + b'"}'
    assert len(body) <= 100

    response = anonymous.post(
        "/api/v1/ai/search", content=body, headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 200


def test_a_chunked_body_over_the_limit_is_refused(anonymous: TestClient) -> None:
    def chunks():
        yield b'{"input": "'
        for _ in range(10):
            yield b"x" * 1024
        yield b'"}'

    # A generator body is sent without Content-Length.
    response = anonymous.post(
        "/api/v1/ai/search", content=chunks(), headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 413


def test_middleware_stops_reading_a_chunked_stream_once_over_the_limit() -> None:
    reached_app = False

    async def app(scope, receive, send) -> None:
        nonlocal reached_app
        reached_app = True

    middleware = BodySizeLimitMiddleware(app, paths={"/limited"}, max_bytes=lambda: 100)
    messages = [{"type": "http.request", "body": b"x" * 60, "more_body": True}] * 5
    received = 0
    sent: list[dict] = []

    async def receive() -> dict:
        nonlocal received
        received += 1
        return messages[received - 1]

    async def send(message: dict) -> None:
        sent.append(message)

    scope = {"type": "http", "path": "/limited", "headers": []}
    asyncio.run(middleware(scope, receive, send))

    assert not reached_app
    assert received == 2  # stopped at 120 bytes, the rest was never read
    assert sent[0]["status"] == 413


def test_other_paths_are_not_limited() -> None:
    reached_app = False

    async def app(scope, receive, send) -> None:
        nonlocal reached_app
        reached_app = True

    middleware = BodySizeLimitMiddleware(app, paths={"/limited"}, max_bytes=lambda: 1)
    scope = {"type": "http", "path": "/other", "headers": [(b"content-length", b"999")]}

    asyncio.run(middleware(scope, None, None))

    assert reached_app


# --- page -------------------------------------------------------------------------------


def test_search_page_is_served_and_uses_public_search(anonymous: TestClient) -> None:
    response = anonymous.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    # The page's search code lives in a module since the B1 front-end; it sends no token.
    search_module = anonymous.get("/static/js/pages/search.js").text
    assert "/api/v1/ai/search" in search_module
    assert "X-Admin-Token" not in response.text + search_module
    assert "admin" not in search_module
