"""Endpoints that embed the request (/ai/search, /ai/ask) while the model is not ready.

Fake loaders only: the real embedding model is never loaded here.
"""

import threading
import time

import pytest
from fastapi.testclient import TestClient

try:
    import app.services.news_search  # noqa: F401  (the endpoints import it on first use)
except (ImportError, OSError) as exc:  # optional ML stack missing or blocked by the OS
    pytest.skip(f"AI dependencies unavailable: {exc}", allow_module_level=True)

from app.core.config import Settings
from app.services import model_preload
from app.services.model_preload import FAILURE_COOLDOWN_SECONDS, ModelLoader

WAIT_SECONDS = 5
ENDPOINTS = ["/api/v1/ai/search", "/api/v1/ai/ask"]
LOADING_DETAIL = "The embedding model is still loading. Try again shortly."


class FakeClock:
    """A clock the test moves forward by hand instead of sleeping."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class FailingLoad:
    """A load function that always fails with `error` and counts its calls."""

    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls = 0

    def __call__(self) -> object:
        self.calls += 1
        raise self.error


def install(monkeypatch: pytest.MonkeyPatch, loader: ModelLoader) -> ModelLoader:
    """Make `loader` the app's shared embedding model loader for this test."""
    monkeypatch.setattr(model_preload, "embedding_model", loader)
    return loader


def ask(client: TestClient, endpoint: str) -> object:
    return client.post(endpoint, json={"input": "latest on G0"})


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_a_request_during_a_load_gets_503_at_once(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, endpoint: str
) -> None:
    started, release = threading.Event(), threading.Event()

    def slow_load() -> object:
        started.set()
        release.wait(WAIT_SECONDS)
        return object()

    thread = install(monkeypatch, ModelLoader(slow_load)).start_background_load()
    try:
        assert started.wait(WAIT_SECONDS)
        began = time.monotonic()
        response = ask(client, endpoint)
        elapsed = time.monotonic() - began
    finally:
        release.set()
        thread.join(WAIT_SECONDS)

    assert response.status_code == 503
    assert response.json() == {"detail": LOADING_DETAIL}
    assert response.headers["Retry-After"] == "10"
    assert elapsed < 2  # answered without waiting for the load


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_any_load_error_is_503(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, endpoint: str
) -> None:
    install(monkeypatch, ModelLoader(FailingLoad(RuntimeError("broken weights"))))

    response = ask(client, endpoint)

    assert response.status_code == 503
    assert "model could not be loaded" in response.json()["detail"]


def test_a_failed_load_is_retried_only_after_the_cooldown(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock, load = FakeClock(), FailingLoad(RuntimeError("broken weights"))
    install(monkeypatch, ModelLoader(load, clock=clock))

    assert ask(client, ENDPOINTS[0]).status_code == 503
    clock.now += FAILURE_COOLDOWN_SECONDS - 0.1
    assert ask(client, ENDPOINTS[0]).status_code == 503
    assert load.calls == 1  # refused during the cooldown, no second load

    clock.now += 0.2
    assert ask(client, ENDPOINTS[0]).status_code == 503
    assert load.calls == 2  # tried again once the cooldown was over


def test_default_embedding_model_is_the_evaluated_minilm() -> None:
    # The class default, so a local .env cannot change the answer.
    default = Settings.model_fields["embedding_model_name"].default

    assert default == "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
