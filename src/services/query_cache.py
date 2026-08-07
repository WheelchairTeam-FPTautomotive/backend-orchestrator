"""Language-aware short-TTL query cache for gateway (#16)."""

from __future__ import annotations

import hashlib
import os
import threading
from typing import Any

from cachetools import TTLCache

# --- START MODIFICATION ---
DEFAULT_TTL_S = 60
DEFAULT_MAXSIZE = 1000


def _ttl_from_env() -> int:
    raw = os.getenv("QUERY_CACHE_TTL_S", str(DEFAULT_TTL_S))
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_TTL_S


class QueryCache:
    """In-process TTL cache keyed by hash(normalized_query):language:intent."""

    def __init__(
        self,
        *,
        ttl_s: int | None = None,
        maxsize: int = DEFAULT_MAXSIZE,
    ) -> None:
        self._lock = threading.Lock()
        self._ttl_s = _ttl_from_env() if ttl_s is None else max(0, ttl_s)
        self._maxsize = max(1, maxsize)
        self._cache: TTLCache[str, dict[str, Any]] | None = None
        if self._ttl_s > 0:
            self._cache = TTLCache(maxsize=self._maxsize, ttl=self._ttl_s)

    @property
    def enabled(self) -> bool:
        return self._cache is not None and self._ttl_s > 0

    @property
    def ttl_s(self) -> int:
        return self._ttl_s

    @staticmethod
    def make_key(normalized_query: str, language: str, intent: str) -> str:
        digest = hashlib.sha256((normalized_query or "").encode("utf-8")).hexdigest()
        return f"{digest}:{language}:{intent}"

    def get(self, key: str) -> dict[str, Any] | None:
        if not self.enabled or self._cache is None:
            return None
        with self._lock:
            value = self._cache.get(key)
            if value is None:
                return None
            # Return a shallow copy so callers cannot mutate the cache entry
            return dict(value)

    def set(self, key: str, payload: dict[str, Any]) -> None:
        if not self.enabled or self._cache is None:
            return
        # Never store bulky audio in text-query cache
        stored = {k: v for k, v in payload.items() if k != "audio_base64"}
        stored["audio_base64"] = None
        with self._lock:
            self._cache[key] = stored

    def clear(self) -> None:
        if self._cache is None:
            return
        with self._lock:
            self._cache.clear()


# Process-wide singleton used by gateway
query_cache = QueryCache()
# --- END MODIFICATION ---
