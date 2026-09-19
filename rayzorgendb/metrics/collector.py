"""
RayzorgenDB Metrics

Track performance metrics in real-time.

Usage:
    from rayzorgendb.metrics import MetricsCollector

    m = MetricsCollector()
    m.record("insert", elapsed_ms=1.5)
    m.summary()  # {"insert": {"count": 1, "avg_ms": 1.5, ...}}
"""

import time
import threading
from collections import defaultdict
from typing import Dict, List


class MetricsCollector:
    """Collect and aggregate metrics."""

    def __init__(self, max_samples: int = 10000):
        self.max_samples = max_samples
        self._data: Dict[str, List[float]] = defaultdict(list)
        self._counters: Dict[str, int] = defaultdict(int)
        self._gauges: Dict[str, float] = {}
        self._timers: Dict[str, float] = {}
        self._lock = threading.RLock()
        self._start_time = time.time()

    def record(self, name: str, value_ms: float):
        """Record a timing sample."""
        with self._lock:
            samples = self._data[name]
            samples.append(value_ms)
            if len(samples) > self.max_samples:
                # Keep last half
                self._data[name] = samples[-self.max_samples // 2:]

    def increment(self, name: str, by: int = 1):
        """Increment a counter."""
        with self._lock:
            self._counters[name] += by

    def set_gauge(self, name: str, value: float):
        """Set a gauge value."""
        with self._lock:
            self._gauges[name] = value

    def timer_start(self, name: str):
        """Start a timer."""
        with self._lock:
            self._timers[name] = time.time()

    def timer_end(self, name: str) -> float:
        """End a timer and record the duration."""
        with self._lock:
            if name not in self._timers:
                return 0.0
            elapsed = (time.time() - self._timers[name]) * 1000
            del self._timers[name]
            self.record(name, elapsed)
            return elapsed

    def summary(self) -> Dict:
        """Return summary of all metrics."""
        with self._lock:
            result = {
                "uptime_sec": round(time.time() - self._start_time, 2),
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "timings": {},
            }
            for name, samples in self._data.items():
                if not samples:
                    continue
                sorted_s = sorted(samples)
                n = len(sorted_s)
                result["timings"][name] = {
                    "count": n,
                    "min_ms": round(sorted_s[0], 3),
                    "max_ms": round(sorted_s[-1], 3),
                    "avg_ms": round(sum(sorted_s) / n, 3),
                    "p50_ms": round(sorted_s[n // 2], 3),
                    "p95_ms": round(
                        sorted_s[int(n * 0.95)], 3
                    ) if n > 1 else round(sorted_s[0], 3),
                    "p99_ms": round(
                        sorted_s[int(n * 0.99)], 3
                    ) if n > 1 else round(sorted_s[0], 3),
                }
            return result

    def reset(self):
        with self._lock:
            self._data.clear()
            self._counters.clear()
            self._gauges.clear()
            self._start_time = time.time()


# Global metrics instance
GLOBAL = MetricsCollector()


def record(name: str, value_ms: float):
    GLOBAL.record(name, value_ms)


def increment(name: str, by: int = 1):
    GLOBAL.increment(name, by)


def summary():
    return GLOBAL.summary()


__all__ = ["MetricsCollector", "GLOBAL", "record",
           "increment", "summary"]
