"""
RayzorgenDB Time-Series Engine

Optimized storage for timestamped metrics.
Auto-downsampling, retention, aggregation.

Usage:
    ts = TimeSeries()
    ts.write("cpu", 45.2)
    ts.write("cpu", 48.1)
    ts.query("cpu", last="1h")
    ts.avg("cpu", last="5m")
"""

import time
import threading
from collections import deque
from typing import Any, Dict, List, Optional, Tuple


class TimeSeries:
    """
    Time-series storage with auto-retention.

    Features:
    - Append-only writes
    - Time-range query
    - Aggregations (avg, min, max, sum, count)
    - Downsampling
    - Retention policy
    """

    def __init__(self, max_points: int = 100000,
                 retention_sec: int = 86400 * 7):
        # {metric: deque of (timestamp, value)}
        self._data: Dict[str, deque] = {}
        self.max_points = max_points
        self.retention_sec = retention_sec
        self._lock = threading.RLock()
        self._stats = {"writes": 0, "reads": 0}

    def write(self, metric: str, value: float,
              timestamp: float = None):
        """Write a data point."""
        ts = timestamp if timestamp is not None else time.time()
        with self._lock:
            if metric not in self._data:
                self._data[metric] = deque(
                    maxlen=self.max_points
                )
            self._data[metric].append((ts, value))
            self._stats["writes"] += 1

    def write_many(self, metric: str,
                   points: List[Tuple[float, float]]):
        """Write multiple points."""
        with self._lock:
            if metric not in self._data:
                self._data[metric] = deque(
                    maxlen=self.max_points
                )
            dq = self._data[metric]
            for ts, val in points:
                dq.append((ts, val))
                self._stats["writes"] += 1

    # --------------------------------------------------------
    # Query
    # --------------------------------------------------------

    def query(self, metric: str,
              start: float = None,
              end: float = None,
              last: str = None,
              limit: int = None) -> List[Tuple[float, float]]:
        """
        Query points by time range.
        last: "5m", "1h", "1d", "1w"
        """
        if last:
            delta = self._parse_duration(last)
            end = time.time()
            start = end - delta
        if start is None:
            start = 0
        if end is None:
            end = time.time()

        with self._lock:
            self._stats["reads"] += 1
            dq = self._data.get(metric, deque())
            result = [
                (ts, v) for ts, v in dq
                if start <= ts <= end
            ]
            if limit:
                result = result[-limit:]
            return result

    def latest(self, metric: str) -> Optional[Tuple[float, float]]:
        with self._lock:
            dq = self._data.get(metric)
            return dq[-1] if dq else None

    def count(self, metric: str) -> int:
        with self._lock:
            return len(self._data.get(metric, ()))

    # --------------------------------------------------------
    # Aggregation
    # --------------------------------------------------------

    def aggregate(self, metric: str, op: str,
                  start: float = None, end: float = None,
                  last: str = None) -> Optional[float]:
        points = self.query(metric, start, end, last)
        if not points:
            return None
        values = [v for _, v in points]
        op = op.lower()
        if op == "sum":
            return sum(values)
        if op == "avg":
            return sum(values) / len(values)
        if op == "min":
            return min(values)
        if op == "max":
            return max(values)
        if op == "count":
            return len(values)
        return None

    def avg(self, metric: str, **kwargs) -> Optional[float]:
        return self.aggregate(metric, "avg", **kwargs)

    def min(self, metric: str, **kwargs) -> Optional[float]:
        return self.aggregate(metric, "min", **kwargs)

    def max(self, metric: str, **kwargs) -> Optional[float]:
        return self.aggregate(metric, "max", **kwargs)

    def sum(self, metric: str, **kwargs) -> Optional[float]:
        return self.aggregate(metric, "sum", **kwargs)

    def rate(self, metric: str, window: str = "1m") -> float:
        """Compute rate of change per second."""
        points = self.query(metric, last=window)
        if len(points) < 2:
            return 0.0
        dt = points[-1][0] - points[0][0]
        dv = points[-1][1] - points[0][1]
        return dv / dt if dt > 0 else 0.0

    # --------------------------------------------------------
    # Downsampling
    # --------------------------------------------------------

    def downsample(self, metric: str, bucket_sec: float,
                   op: str = "avg") -> List[Tuple[float, float]]:
        """Downsample by time bucket."""
        points = self.query(metric)
        if not points:
            return []

        buckets: Dict[int, List[float]] = {}
        for ts, v in points:
            bucket = int(ts / bucket_sec)
            buckets.setdefault(bucket, []).append(v)

        result = []
        for bucket_id, values in sorted(buckets.items()):
            bucket_ts = bucket_id * bucket_sec
            if op == "avg":
                agg = sum(values) / len(values)
            elif op == "sum":
                agg = sum(values)
            elif op == "min":
                agg = min(values)
            elif op == "max":
                agg = max(values)
            elif op == "count":
                agg = float(len(values))
            else:
                agg = values[0]
            result.append((bucket_ts, agg))
        return result

    # --------------------------------------------------------
    # Retention
    # --------------------------------------------------------

    def apply_retention(self):
        """Remove old points beyond retention."""
        cutoff = time.time() - self.retention_sec
        removed = 0
        with self._lock:
            for metric, dq in self._data.items():
                # Keep recent
                new_dq = deque(
                    (p for p in dq if p[0] >= cutoff),
                    maxlen=self.max_points,
                )
                removed += len(dq) - len(new_dq)
                self._data[metric] = new_dq
        return removed

    # --------------------------------------------------------
    # Metrics
    # --------------------------------------------------------

    def metrics(self) -> List[str]:
        with self._lock:
            return list(self._data.keys())

    def stats(self) -> Dict:
        with self._lock:
            total = sum(len(d) for d in self._data.values())
            return {
                **self._stats,
                "metrics": len(self._data),
                "total_points": total,
                "retention_sec": self.retention_sec,
            }

    # --------------------------------------------------------
    # Helpers
    # --------------------------------------------------------

    @staticmethod
    def _parse_duration(s: str) -> float:
        if not s:
            return 0
        unit = s[-1].lower()
        try:
            n = float(s[:-1])
        except ValueError:
            return 0
        return n * {
            "s": 1,
            "m": 60,
            "h": 3600,
            "d": 86400,
            "w": 604800,
        }.get(unit, 1)


__all__ = ["TimeSeries"]
