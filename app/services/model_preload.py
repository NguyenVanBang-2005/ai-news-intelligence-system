"""Load the embedding model once, optionally in a background thread at startup.

Kept free of ML imports at module level: /health reads `embedding_model.ready` and the
app must still start when torch / sentence-transformers are missing or blocked.
"""

import logging
import threading
from collections.abc import Callable

logger = logging.getLogger(__name__)


class ModelLoader:
    """Calls `load` once. A caller that arrives during a load waits for it instead of
    loading a second copy. A failed load is not remembered, so the next call retries."""

    def __init__(self, load: Callable[[], object]):
        self._load = load
        self._lock = threading.Lock()
        self._model: object | None = None

    @property
    def ready(self) -> bool:
        return self._model is not None

    def get(self) -> object:
        if self._model is None:
            with self._lock:
                if self._model is None:  # another thread may have loaded it meanwhile
                    self._model = self._load()
        return self._model

    def start_background_load(self) -> threading.Thread:
        """Loads in a daemon thread; errors are logged, never raised."""
        thread = threading.Thread(target=self._load_and_log, name="model-preload", daemon=True)
        thread.start()
        return thread

    def _load_and_log(self) -> None:
        try:
            self.get()
        except Exception:
            logger.exception("Embedding model preload failed; search will try again on demand.")
        else:
            logger.info("Embedding model preloaded.")


def load_search_model() -> object:
    """Imports the search code (slow: torch, sentence-transformers), then builds the model."""
    from sentence_transformers import SentenceTransformer

    import app.services.news_search  # noqa: F401  (warms the imports of POST /ai/search)
    from app.core.config import settings

    return SentenceTransformer(settings.embedding_model_name)


embedding_model = ModelLoader(load_search_model)
