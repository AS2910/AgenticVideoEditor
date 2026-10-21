"""A small in-memory rate limit (G7, G8): at most `limit` hits per `window`
seconds for one key (an owner, an address). Enough for one server; a fleet
would put this in shared storage."""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable


class RateLimit:
    def __init__(self, limit: int, window: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.limit, self.window, self.clock = limit, window, clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        """Count one hit for `key`; False when it is over the limit (the hit is not counted)."""
        now = self.clock()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= now - self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            if len(self._hits) > 10_000:            # forget idle keys
                for k in [k for k, d in self._hits.items() if not d or d[-1] <= now - self.window]:
                    self._hits.pop(k, None)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
