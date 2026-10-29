"""AI_PRELOAD_MODEL: background model loading at startup, loaded once, never fatal.

Fake loaders only: the real embedding model is never loaded here.
"""

import ast
import logging
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services import model_preload
from app.services.model_preload import ModelLoader

WAIT_SECONDS = 5


class CountingLoad:
    """A fake load function: counts calls, can be slow, can fail."""

    def __init__(self, delay: float = 0.0, error: Exception | None = None):
        self.calls = 0
        self.delay = delay
        self.error = error
        self._lock = threading.Lock()

    def __call__(self) -> object:
        with self._lock:
            self.calls += 1
        time.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return object()


@pytest.fixture
def use_loader(monkeypatch: pytest.MonkeyPatch):
    """Installs a ModelLoader around the given fake load function and returns it."""

    def install(load: CountingLoad) -> ModelLoader:
        loader = ModelLoader(load)
        monkeypatch.setattr(model_preload, "embedding_model", loader)
        return loader

    return install


def wait_until(condition, seconds: float = WAIT_SECONDS) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.01)
    return False


def preload_threads() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t.name == "model-preload"]


# --- startup -----------------------------------------------------------------------------


def test_no_preload_when_the_flag_is_off(use_loader) -> None:
    load = CountingLoad()
    loader = use_loader(load)

    with TestClient(app) as client:
        assert client.get("/api/v1/health").json()["model_ready"] is False

    assert load.calls == 0 and not loader.ready


def test_preload_loads_once_in_the_background(use_loader, monkeypatch) -> None:
    monkeypatch.setattr(settings, "ai_preload_model", True)
    load = CountingLoad(delay=0.3)
    loader = use_loader(load)

    with TestClient(app) as client:
        # Startup did not wait for the slow load: requests are answered meanwhile.
        assert client.get("/api/v1/health").json()["model_ready"] is False
        assert wait_until(lambda: loader.ready)
        assert client.get("/api/v1/health").json()["model_ready"] is True

    assert load.calls == 1


def test_failed_preload_is_logged_and_startup_still_works(use_loader, monkeypatch, caplog) -> None:
    monkeypatch.setattr(settings, "ai_preload_model", True)
    load = CountingLoad(error=OSError("no network"))
    use_loader(load)

    with caplog.at_level(logging.ERROR, logger="app.services.model_preload"):
        with TestClient(app) as client:
            assert wait_until(lambda: load.calls == 1 and not preload_threads())
            response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "model_ready": False}
    assert "preload failed" in caplog.text


# --- ModelLoader -------------------------------------------------------------------------


def test_two_concurrent_callers_load_once() -> None:
    load = CountingLoad(delay=0.2)
    loader = ModelLoader(load)
    results: list[object] = []
    callers = [threading.Thread(target=lambda: results.append(loader.get())) for _ in range(2)]

    for caller in callers:
        caller.start()
    for caller in callers:
        caller.join(timeout=WAIT_SECONDS)

    assert load.calls == 1
    assert len(results) == 2 and results[0] is results[1]


def test_a_caller_during_the_background_load_waits_for_it() -> None:
    load = CountingLoad(delay=0.2)
    loader = ModelLoader(load)

    thread = loader.start_background_load()
    model = loader.get()
    thread.join(timeout=WAIT_SECONDS)

    assert load.calls == 1 and loader.get() is model


def test_a_failed_load_is_retried_by_the_next_caller() -> None:
    load = CountingLoad(error=OSError("no network"))
    loader = ModelLoader(load)

    for _ in range(2):
        with pytest.raises(OSError):
            loader.get()

    assert load.calls == 2 and not loader.ready


def test_get_embedding_model_goes_through_the_shared_loader() -> None:
    # Read the source instead of importing app.services.embeddings, which imports torch
    # (about 25 s) and would make this test slow.
    source = (Path(model_preload.__file__).parent / "embeddings.py").read_text(encoding="utf-8")
    function = next(node for node in ast.parse(source).body
                    if isinstance(node, ast.FunctionDef) and node.name == "get_embedding_model")

    assert "model_preload.embedding_model.get()" in ast.unparse(function)
    assert "lru_cache" not in source
