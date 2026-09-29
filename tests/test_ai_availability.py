import builtins
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app
from tests.db_isolation import isolated_env

STARTUP_SCRIPT = """
import importlib.abc
import sys

class BlockAI(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {
            'bertopic', 'sklearn', 'sentence_transformers', 'torch', 'hdbscan', 'umap'
        }:
            raise ImportError('Simulated Application Control block')

sys.meta_path.insert(0, BlockAI())
from alembic import command
from alembic.config import Config
command.upgrade(Config('alembic.ini'), 'head')
from fastapi.testclient import TestClient
from app.main import app
with TestClient(app) as client:
    assert client.get('/api/v1/health').status_code == 200
    assert client.get('/api/v1/articles').status_code == 200
    assert client.get('/openapi.json').status_code == 200
assert 'app.services.topic_model' not in sys.modules
"""


def run_startup_script(tmp_path: Path) -> tuple[subprocess.CompletedProcess, Path]:
    db_file = tmp_path / "startup.db"
    # Use a file database so TestClient threads share the same isolated data.
    env = isolated_env(f"sqlite:///{db_file.as_posix()}")
    result = subprocess.run(
        [sys.executable, "-c", STARTUP_SCRIPT],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result, db_file


def test_startup_does_not_import_optional_ai_dependencies(tmp_path: Path) -> None:
    result, _ = run_startup_script(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr


def test_startup_ignores_ambient_postgres_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("POSTGRES_HOST", "postgres-must-not-be-used.invalid")
    monkeypatch.setenv("POSTGRES_PASSWORD", "secret")

    result, db_file = run_startup_script(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert db_file.exists()  # migration and startup used the temporary SQLite file


@pytest.mark.parametrize("error_type", [ImportError, OSError])
def test_ai_dependency_failure_returns_503(monkeypatch, error_type) -> None:
    original_import = builtins.__import__

    def blocked_import(name, *args, **kwargs):
        if name == "app.services.topic_model":
            raise error_type("Simulated blocked native DLL")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_import)
    app.dependency_overrides[get_db] = lambda: None
    client = TestClient(app)
    try:
        # No lifespan: this request must fail before any DB or model access.
        response = client.post("/api/v1/ai/process", json={})
        health = client.get("/api/v1/health")
    finally:
        client.close()
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 503
    assert "AI dependencies could not be loaded" in response.json()["detail"]
    assert health.status_code == 200
