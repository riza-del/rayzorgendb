"""
RayzorgenDB Query Optimizer

Cost-based optimizer with statistics and plan selection.
"""

import time
import threading
from typing import Any, Dict, List, Optional


class Statistics:
    """Collect and store statistics per collection."""

    def __init__(self):
        self._stats: Dict[str, Dict] = {}
        self._lock = threading.RLock()

    def update(self, collection: str, field: str,
               total_rows: int, distinct: int,
               min_val=None, max_val=None):
        with self._lock:
            self._stats.setdefault(collection, {})
            self._stats[collection][field] = {
                "total_rows": total_rows,
                "distinct": distinct,
                "selectivity": (
                    distinct / total_rows
                    if total_rows > 0 else 1.0
                ),
                "min": min_val,
                "max": max_val,
                "updated_at": time.time(),
            }

    def analyze(self, core, collection: str):
        """Analyze a collection and store field statistics."""
        data = core._data.get(collection, {})
        total = len(data)
        if total == 0:
            return

        field_values: Dict[str, List] = {}
        for raw in data.values():
            d = raw.get("data", {})
            for k, v in d.items():
                if isinstance(v, (str, int, float, bool)):
                    field_values.setdefault(k, []).append(v)

        for field, values in field_values.items():
            distinct = len(set(values))
            try:
                min_v = min(values) if values else None
                max_v = max(values) if values else None
            except TypeError:
                min_v = max_v = None
            self.update(collection, field, total,
                        distinct, min_v, max_v)

    def get(self, collection: str,
            field: str) -> Optional[Dict]:
        with self._lock:
            return self._stats.get(
                collection, {}
            ).get(field)

    def all(self, collection: str) -> Dict:
        with self._lock:
            return dict(self._stats.get(collection, {}))

    def clear(self, collection: str = None):
        with self._lock:
            if collection:
                self._stats.pop(collection, None)
            else:
                self._stats.clear()


class PlanNode:
    """A node in the execution plan tree."""

    def __init__(self, op: str, cost: float = 0,
                 rows: int = 0, details: Dict = None,
                 children: List = None):
        self.op = op
        self.cost = cost
        self.rows = rows
        self.details = details or {}
        self.children = children or []

    def to_dict(self) -> Dict:
        return {
            "op": self.op,
            "cost": round(self.cost, 2),
            "rows": self.rows,
            "details": self.details,
            "children": [c.to_dict() for c in self.children],
        }

    def explain(self, indent: int = 0) -> str:
        prefix = "  " * indent
        line = (
            prefix + self.op +
            "  (cost=" + str(round(self.cost, 1)) +
            ", rows=" + str(self.rows) + ")"
        )
        if self.details:
            extras = []
            for k, v in self.details.items():
                if isinstance(v, (str, int, float)):
                    extras.append(str(k) + "=" + str(v))
            if extras:
                line += "  " + " ".join(extras)
        lines = [line]
        for c in self.children:
            lines.append(c.explain(indent + 1))
        return "\n".join(lines)


class QueryOptimizer:
    """Cost-based query optimizer."""

    def __init__(self, core):
        self.core = core
        self.stats = Statistics()
        self._lock = threading.RLock()

    def analyze(self, collection: str):
        self.stats.analyze(self.core, collection)

    def optimize_select(self, collection: str,
                         filters: List[Dict],
                         order_by: str = None,
                         limit: int = None,
                         index_manager=None) -> PlanNode:
        """
        Build an execution plan.
        filters: [{"field": ..., "op": ..., "value": ...}, ...]
        """
        total = len(self.core._data.get(collection, {}))

        # Base: full scan
        plan = PlanNode(
            op="SeqScan",
            cost=float(total),
            rows=total,
            details={"table": collection},
        )

        # Cari index yang bisa dipakai
        if index_manager is not None:
            hashed = index_manager.list_indexes(collection)
            sorted_idx = index_manager.list_sorted_indexes(
                collection
            )
        else:
            hashed = []
            sorted_idx = []

        used_index = None
        remaining_filters = []

        for f in filters:
            field = f.get("field")
            op = f.get("op", "eq")
            value = f.get("value")

            # Hash index for equality
            if op == "eq" and field in hashed:
                rows = 1
                try:
                    rows = len(
                        index_manager.search(
                            collection, field, value
                        )
                    )
                except Exception:
                    pass
                plan = PlanNode(
                    op="IndexScan",
                    cost=1.0 + rows,
                    rows=rows,
                    details={
                        "table": collection,
                        "field": field,
                        "value": value,
                        "index": "hash",
                    },
                    children=[plan],
                )
                used_index = field
            # B+ Tree for range
            elif op in ("gt", "lt", "gte", "lte",
                        "between") and field in sorted_idx:
                # Estimate range size
                field_stats = self.stats.get(collection, field)
                est = total // 4  # default guess
                if field_stats:
                    sel = field_stats.get("selectivity", 0.5)
                    est = max(1, int(total * sel))
                plan = PlanNode(
                    op="RangeScan",
                    cost=2.0 + est * 0.1,
                    rows=est,
                    details={
                        "table": collection,
                        "field": field,
                        "op": op,
                        "index": "btree",
                    },
                    children=[plan],
                )
                used_index = field
            else:
                remaining_filters.append(f)

        # Apply remaining filters
        rows_so_far = plan.rows
        for f in remaining_filters:
            field = f.get("field")
            op = f.get("op", "eq")
            field_stats = self.stats.get(collection, field)
            selectivity = 0.5
            if field_stats:
                selectivity = max(
                    0.01,
                    field_stats.get("selectivity", 0.5)
                )
            if op == "eq":
                selectivity = min(selectivity, 0.1)
            elif op in ("gt", "lt", "gte", "lte"):
                selectivity = 0.3
            elif op == "between":
                selectivity = 0.2
            elif op in ("contains", "icontains"):
                selectivity = 0.5

            new_rows = max(1, int(rows_so_far * selectivity))
            plan = PlanNode(
                op="Filter",
                cost=plan.cost + rows_so_far * 0.1,
                rows=new_rows,
                details={
                    "field": field,
                    "op": op,
                    "value": str(f.get("value"))[:20],
                },
                children=[plan],
            )
            rows_so_far = new_rows

        # Sort
        if order_by:
            import math
            sort_cost = rows_so_far * math.log2(
                max(rows_so_far, 2)
            )
            plan = PlanNode(
                op="Sort",
                cost=plan.cost + sort_cost,
                rows=rows_so_far,
                details={"field": order_by},
                children=[plan],
            )

        # Limit
        if limit:
            plan = PlanNode(
                op="Limit",
                cost=plan.cost * (limit / max(rows_so_far, 1)),
                rows=min(limit, rows_so_far),
                details={"limit": limit},
                children=[plan],
            )

        return plan

    def explain(self, plan: PlanNode) -> str:
        return plan.explain()


__all__ = ["QueryOptimizer", "PlanNode", "Statistics"]
