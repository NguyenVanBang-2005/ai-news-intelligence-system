"""In-memory sliding-window rate limiter.

The counters live in this process only: with several workers or replicas each one keeps its
own window, so a client can make up to `limit` requests per worker. Use a shared store
(e.g. Redis) when the app is scaled out.
"""

import math
import threading
import time
from collections import deque
from collections.abc import Callable

# Forget idle clients once this many are tracked, so the table cannot grow without bound.
MAX_TRACKED_KEYS = 10_000


class SlidingWindowRateLimiter:
    def __init__(self, *, window_seconds: float, clock: Callable[[], float] = time.monotonic):
        self.window_seconds = window_seconds
        # Replaceable so tests can move time forward.
        self.clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int) -> int | None:
        """Record one request for `key`. Returns None when it is allowed, otherwise the
        whole seconds until the oldest request in the window expires (for Retry-After)."""

        now = self.clock()
        window_start = now - self.window_seconds

        with self._lock:
            if len(self._hits) >= MAX_TRACKED_KEYS:
                self._forget_idle(window_start)

            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= window_start:
                hits.popleft()

            if len(hits) >= limit:
                return max(1, math.ceil(hits[0] + self.window_seconds - now))

            hits.append(now)
            return None

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()

    def _forget_idle(self, window_start: float) -> None:
        for key in [key for key, hits in self._hits.items() if not hits or hits[-1] <= window_start]:
            del self._hits[key]
