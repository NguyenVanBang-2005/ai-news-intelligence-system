import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import model_preload
from app.services.model_preload import ModelLoader


@pytest.fixture
def fresh_loader(monkeypatch: pytest.MonkeyPatch) -> ModelLoader:
    """A loader no other test has used, with a fake model."""
    loader = ModelLoader(lambda: object())
    monkeypatch.setattr(model_preload, "embedding_model", loader)
    return loader


def test_health(fresh_loader: ModelLoader) -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    # model_ready is information only; health is "ok" without the model.
    assert response.json() == {"status": "ok", "model_ready": False}


def test_health_reports_a_loaded_model(fresh_loader: ModelLoader) -> None:
    fresh_loader.get()

    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    assert response.json() == {"status": "ok", "model_ready": True}
