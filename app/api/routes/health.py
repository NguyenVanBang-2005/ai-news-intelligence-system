from fastapi import APIRouter

from app.services import model_preload

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict[str, str | bool]:
    """Liveness. `model_ready` is information only: the API is healthy without the model."""
    return {"status": "ok", "model_ready": model_preload.embedding_model.ready}

