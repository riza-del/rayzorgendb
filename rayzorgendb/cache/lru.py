"""
RayzorgenDB Cache Layer
LRU cache with TTL for query results and records.
"""

import time
import threading
from collections import OrderedDict
from typing import Any, Optional


class LRUCache:
    """
    Thread-safe LRU cache with optional TTL.

    Features:
    - O(1) get/set
    - Automatic eviction when full
    - Optional time-to-live per entry
    - Hit/miss statistics
    """

    def __init__(self, max_size: int = 1000,
                 default_ttl: float = None):
        self.max_size = max_size
        self.default_ttl = default_ttl
        self._store: OrderedDict = OrderedDict()
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    def get(self, key: Any) -> Optional[Any]:
        """Get value, returns None if missing or expired."""
        with self._lock:
            if key not in self._store:
                self._misses += 1
                return None

            value, expires_at = self._store[key]

            if expires_at is not None and time.time() > expires_at:
                del self._store[key]
                self._misses += 1
                return None

            # Move to end (most recently used)
            self._store.move_to_end(key)
            self._hits += 1
            return value

    def set(self, key: Any, value: Any,
            ttl: float = None):
        """Set a value with optional TTL."""
        with self._lock:
            if ttl is None:
                ttl = self.default_ttl

            expires_at = None
            if ttl is not None:
                expires_at = time.time() + ttl

            if key in self._store:
                del self._store[key]

            self._store[key] = (value, expires_at)

            # Evict if over capacity
            while len(self._store) > self.max_size:
                self._store.popitem(last=False)
                self._evictions += 1

    def invalidate(self, key: Any):
        """Remove a specific key."""
        with self._lock:
            self._store.pop(key, None)

    def invalidate_prefix(self, prefix: str):
        """Remove all keys starting with prefix."""
        with self._lock:
            to_remove = [
                k for k in self._store.keys()
                if isinstance(k, str) and k.startswith(prefix)
            ]
            for k in to_remove:
                del self._store[k]

    def clear(self):
        """Remove all entries."""
        with self._lock:
            self._store.clear()

    def cleanup_expired(self):
        """Remove expired entries."""
        with self._lock:
            now = time.time()
            to_remove = [
                k for k, (_, exp) in self._store.items()
                if exp is not None and now > exp
            ]
            for k in to_remove:
                del self._store[k]

    def stats(self) -> dict:
        """Cache statistics."""
        with self._lock:
            total = self._hits + self._misses
            hit_ratio = (
                self._hits / total if total > 0 else 0.0
            )
            return {
                "size": len(self._store),
                "max_size": self.max_size,
                "hits": self._hits,
                "misses": self._misses,
                "evictions": self._evictions,
                "hit_ratio": round(hit_ratio, 4),
            }

    def reset_stats(self):
        with self._lock:
            self._hits = 0
            self._misses = 0
            self._evictions = 0

    def __len__(self):
        with self._lock:
            return len(self._store)

    def __contains__(self, key):
        with self._lock:
            if key not in self._store:
                return False
            _, expires_at = self._store[key]
            if expires_at is not None and time.time() > expires_at:
                del self._store[key]
                return False
            return True


class QueryCache:
    """
    Specialized cache for query results.
    Keys are computed from query parameters.
    """

    def __init__(self, max_size: int = 500,
                 ttl: float = 60.0):
        self.cache = LRUCache(max_size=max_size,
                              default_ttl=ttl)
        self._collection_versions = {}
        self._lock = threading.RLock()

    def _key(self, collection: str, operation: str,
             params: tuple) -> str:
        # Include collection version so we invalidate on writes
        version = self._collection_versions.get(collection, 0)
        return "{}:{}:{}:{}".format(
            collection, version, operation, hash(params)
        )

    def get(self, collection: str, operation: str,
            params: tuple) -> Optional[Any]:
        key = self._key(collection, operation, params)
        return self.cache.get(key)

    def set(self, collection: str, operation: str,
            params: tuple, value: Any):
        key = self._key(collection, operation, params)
        self.cache.set(key, value)

    def invalidate_collection(self, collection: str):
        """Call this when the collection changes."""
        with self._lock:
            self._collection_versions[collection] =                 self._collection_versions.get(collection, 0) + 1

    def clear(self):
        self.cache.clear()

    def stats(self) -> dict:
        return self.cache.stats()
