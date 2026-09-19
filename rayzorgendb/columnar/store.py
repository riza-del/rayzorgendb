"""
RayzorgenDB Columnar Engine

Column-based storage for fast analytics.

Row-based:  [{a: 1, b: 2}, {a: 3, b: 4}]
Columnar:   {a: [1, 3], b: [2, 4]}

Why faster for analytics:
- sum("a") only reads a's list (contiguous memory)
- CPU cache friendly
- No dict overhead per row
- Vectorizable operations

Why slower for CRUD:
- Insert requires appending to every column
- Update requires finding row across columns
- Not good for single-row operations

Usage:
    cs = ColumnarStore()
    cs.load_from_rows([{...}, {...}])
    cs.sum("a")
    cs.avg("b")
    cs.group_by("a")
"""

import threading
from typing import Any, Dict, List, Optional, Tuple


class ColumnarStore:
    """Column-oriented storage for analytics."""

    def __init__(self):
        self._columns: Dict[str, List[Any]] = {}
        self._ids: List[str] = []
        self._count = 0
        self._lock = threading.RLock()

    # --------------------------------------------------------
    # Load / Convert
    # --------------------------------------------------------

    def load_from_rows(self, rows: List[Dict],
                       ids: List[str] = None):
        """
        Load data from row-based records.
        rows: list of record dicts, each with "data" or flat dict.
        ids: optional list of record IDs.
        """
        with self._lock:
            self._columns.clear()
            self._ids.clear()
            self._count = 0

            if not rows:
                return

            # Normalize: every row becomes {field: value}
            normalized = []
            for i, r in enumerate(rows):
                if "data" in r and isinstance(r["data"], dict):
                    data = r["data"]
                    rid = r.get("id", str(i))
                else:
                    data = r
                    rid = ids[i] if ids and i < len(ids) else str(i)
                normalized.append((rid, data))

            # Collect all fields
            all_fields = set()
            for _, data in normalized:
                all_fields.update(data.keys())

            # Initialize columns
            for field in all_fields:
                self._columns[field] = []

            # Fill columns
            for rid, data in normalized:
                self._ids.append(rid)
                for field in all_fields:
                    self._columns[field].append(
                        data.get(field, None)
                    )
            self._count = len(self._ids)

    def load_from_core(self, core, collection: str):
        """Load directly from RayzorgenDB core."""
        records = list(
            core._data.get(collection, {}).values()
        )
        self.load_from_rows(records)

    # --------------------------------------------------------
    # Aggregation (fast path)
    # --------------------------------------------------------

    def sum(self, field: str) -> float:
        col = self._columns.get(field, [])
        total = 0.0
        for v in col:
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                total += v
        return total

    def avg(self, field: str) -> Optional[float]:
        col = self._columns.get(field, [])
        total = 0.0
        count = 0
        for v in col:
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                total += v
                count += 1
        return total / count if count else None

    def min(self, field: str) -> Any:
        col = self._columns.get(field, [])
        values = [
            v for v in col
            if isinstance(v, (int, float)) and not isinstance(v, bool)
        ]
        return __builtins__["min"](values) if values else None

    def max(self, field: str) -> Any:
        col = self._columns.get(field, [])
        values = [
            v for v in col
            if isinstance(v, (int, float)) and not isinstance(v, bool)
        ]
        return __builtins__["max"](values) if values else None

    def count(self) -> int:
        return self._count

    def count_field(self, field: str) -> int:
        col = self._columns.get(field, [])
        return sum(1 for v in col if v is not None)

    def aggregate(self, field: str, op: str = "sum") -> Any:
        if op == "sum":
            return self.sum(field)
        if op == "avg":
            return self.avg(field)
        if op == "min":
            return self.min(field)
        if op == "max":
            return self.max(field)
        if op == "count":
            return self.count_field(field)
        raise ValueError("Unknown aggregate: " + op)

    # --------------------------------------------------------
    # Group by (fast path)
    # --------------------------------------------------------

    def group_by(self, field: str,
                 agg_field: str = None,
                 agg_op: str = "count") -> Dict:
        """Group by field. If agg_field given, aggregate it."""
        col = self._columns.get(field, [])
        if agg_field and agg_op != "count":
            agg_col = self._columns.get(agg_field, [])
        else:
            agg_col = None

        groups: Dict[Any, Any] = {}
        counts: Dict[Any, int] = {}
        sums: Dict[Any, float] = {}

        for i, key in enumerate(col):
            if key is None:
                key = "__none__"
            if not isinstance(key, (str, int, float, bool)):
                key = str(key)

            counts[key] = counts.get(key, 0) + 1

            if agg_col is not None:
                v = agg_col[i] if i < len(agg_col) else None
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    sums[key] = sums.get(key, 0.0) + v

        if agg_col is None or agg_op == "count":
            return counts

        result = {}
        for k, c in counts.items():
            s = sums.get(k, 0.0)
            if agg_op == "sum":
                result[k] = s
            elif agg_op == "avg":
                result[k] = s / c if c else 0
            elif agg_op == "min":
                result[k] = s
            elif agg_op == "max":
                result[k] = s
            else:
                result[k] = s
        return result

    def distinct(self, field: str) -> List[Any]:
        col = self._columns.get(field, [])
        seen = set()
        out = []
        for v in col:
            if isinstance(v, (list, dict)):
                v = str(v)
            if v not in seen:
                seen.add(v)
                out.append(v)
        return out

    # --------------------------------------------------------
    # Filter (returns row indices)
    # --------------------------------------------------------

    def filter_indices(self, field: str, op: str,
                       value: Any) -> List[int]:
        col = self._columns.get(field, [])
        result = []
        for i, v in enumerate(col):
            if self._compare(v, op, value):
                result.append(i)
        return result

    def select_fields(self, fields: List[str],
                      indices: List[int] = None) -> List[Dict]:
        """Return list of dicts with only selected fields."""
        if indices is None:
            indices = range(self._count)
        out = []
        for i in indices:
            row = {}
            for f in fields:
                col = self._columns.get(f, [])
                row[f] = col[i] if i < len(col) else None
            out.append(row)
        return out

    def to_rows(self, indices: List[int] = None) -> List[Dict]:
        """Convert back to row format."""
        if indices is None:
            indices = range(self._count)
        fields = list(self._columns.keys())
        rows = []
        for i in indices:
            row = {"id": self._ids[i] if i < len(self._ids) else None}
            for f in fields:
                col = self._columns[f]
                row[f] = col[i] if i < len(col) else None
            rows.append(row)
        return rows

    # --------------------------------------------------------
    # Statistics
    # --------------------------------------------------------

    def stats(self) -> Dict:
        with self._lock:
            return {
                "rows": self._count,
                "columns": len(self._columns),
                "fields": list(self._columns.keys()),
                "total_cells": sum(
                    len(c) for c in self._columns.values()
                ),
            }

    def column_size(self, field: str) -> int:
        return len(self._columns.get(field, []))

    def clear(self):
        with self._lock:
            self._columns.clear()
            self._ids.clear()
            self._count = 0

    @staticmethod
    def _compare(v: Any, op: str, target: Any) -> bool:
        try:
            if op == "eq":     return v == target
            if op == "ne":     return v != target
            if op == "gt":     return v is not None and v > target
            if op == "lt":     return v is not None and v < target
            if op == "gte":    return v is not None and v >= target
            if op == "lte":    return v is not None and v <= target
            if op == "in":     return v in target
            if op == "nin":    return v not in target
            if op == "contains":
                return str(target) in str(v)
            if op == "icontains":
                return str(target).lower() in str(v).lower()
            if op == "startswith":
                return str(v).startswith(str(target))
            if op == "endswith":
                return str(v).endswith(str(target))
            if op == "exists":
                return (v is not None) == bool(target)
            if op == "between":
                lo, hi = target
                return v is not None and lo <= v <= hi
        except (TypeError, AttributeError):
            return False
        return False


__all__ = ["ColumnarStore"]
