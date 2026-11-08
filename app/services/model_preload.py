"""Load the embedding model once, optionally in a background thread at startup.

Kept free of ML imports at module level: /health reads `embedding_model.ready` and the
app must still start when torch / sentence-transformers are missing or blocked.
"""

import logging
import threading
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)

# After a failed load, callers that must not wait are refused for this long
# instead of paying for another (slow, probably failing) load attempt.
FAILURE_COOLDOWN_SECONDS = 30.0


class ModelLoadingError(RuntimeError):
    """Another caller (the startup preload or a request) is loading the model right now."""


class ModelLoadFailedRecentlyError(RuntimeError):
    """The last load failed less than FAILURE_COOLDOWN_SECONDS ago."""


class ModelLoader:
    """Calls `load` once and keeps the model. `get` waits for a load in progress;
    `get_without_waiting` refuses instead. A failed load is not kept: a later call retries."""

    def __init__(self, load: Callable[[], object], clock: Callable[[], float] = time.monotonic):
        self._load = load
        self._clock = clock
        self._lock = threading.Lock()
        self._model: object | None = None
        self._last_failure_at: float | None = None

    @property
    def ready(self) -> bool:
        return self._model is not None

    def get(self) -> object:
        """The model; loads it, or waits for the load already in progress."""
        if self._model is None:
            with self._lock:
                self._load_if_missing()
        return self._model

    def get_without_waiting(self) -> object:
        """The model; loads it if nobody else is loading it, but never waits for them.

        Raises ModelLoadingError during someone else's load and ModelLoadFailedRecentlyError
        during the cooldown after a failed load.
        """
        if self._model is not None:
            return self._model
        if self._failed_recently():
            raise ModelLoadFailedRecentlyError("The embedding model failed to load recently.")
        if not self._lock.acquire(blocking=False):
            raise ModelLoadingError("The embedding model is still loading.")
        try:
            self._load_if_missing()
        finally:
            self._lock.release()
        return self._model

    def _load_if_missing(self) -> None:
        """Runs `load` unless a model is already there; the caller holds the lock."""
        if self._model is not None:  # another thread may have loaded it meanwhile
            return
        try:
            self._model = self._load()
        except Exception:
            self._last_failure_at = self._clock()
            raise
        self._last_failure_at = None

    def _failed_recently(self) -> bool:
        """Whether the last load failed less than FAILURE_COOLDOWN_SECONDS ago."""
        failed_at = self._last_failure_at
        return failed_at is not None and self._clock() - failed_at < FAILURE_COOLDOWN_SECONDS

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
