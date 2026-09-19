"""
RayzorgenDB Query History & Slow Query Log

Track every query for monitoring and debugging.
"""

import time
import threading
from collections import deque
from typing import Any, Dict, List, Optional


class QueryHistory:
    """
    Track query history.
    - All queries (ring buffer)
    - Slow queries (above threshold)
    """

    def __init__(self, max_history: int = 1000,
                 slow_threshold_ms: float = 100.0):
        self.max_history = max_history
        self.slow_threshold_ms = slow_threshold_ms
        self._history = deque(maxlen=max_history)
        self._slow = deque(maxlen=100)
        self._lock = threading.RLock()
        self._stats = {
            "total_queries": 0,
            "slow_queries": 0,
            "errors": 0,
            "total_time_ms": 0.0,
        }

    def record(self, query: str, duration_ms: float,
               rows: int = 0, error: str = None,
               source: str = "python"):
        """Record a query execution."""
        with self._lock:
            entry = {
                "query": query[:200],
                "duration_ms": round(duration_ms, 3),
                "rows": rows,
                "source": source,
                "at": time.time(),
                "error": error,
            }
            self._history.append(entry)

            self._stats["total_queries"] += 1
            self._stats["total_time_ms"] += duration_ms

            if error:
                self._stats["errors"] += 1

            if duration_ms >= self.slow_threshold_ms:
                self._slow.append(entry)
                self._stats["slow_queries"] += 1

    def recent(self, n: int = 20) -> List[Dict]:
        with self._lock:
            return list(self._history)[-n:]

    def slow(self, n: int = 20) -> List[Dict]:
        with self._lock:
            return list(self._slow)[-n:]

    def stats(self) -> Dict:
        with self._lock:
            total = self._stats["total_queries"]
            avg = (
                self._stats["total_time_ms"] / total
                if total > 0 else 0
            )
            return {
                **self._stats,
                "avg_time_ms": round(avg, 3),
                "threshold_ms": self.slow_threshold_ms,
            }

    def clear(self):
        with self._lock:
            self._history.clear()
            self._slow.clear()
            self._stats = {
                "total_queries": 0,
                "slow_queries": 0,
                "errors": 0,
                "total_time_ms": 0.0,
            }


# Global instance
_GLOBAL = QueryHistory()


def record(query: str, duration_ms: float, **kwargs):
    _GLOBAL.record(query, duration_ms, **kwargs)


def recent(n: int = 20):
    return _GLOBAL.recent(n)


def slow(n: int = 20):
    return _GLOBAL.slow(n)


def stats():
    return _GLOBAL.stats()


__all__ = [
    "QueryHistory", "record", "recent", "slow", "stats",
]
