"""
RayzorgenDB Superposition Query

Query many conditions simultaneously.
Results are scored, not filtered.

Unlike binary WHERE (match / no match), superposition
returns a ranking based on how well each record matches
the ensemble of conditions.

Inspired by information retrieval, fuzzy logic, and
weighted scoring systems.
"""

import math
from typing import Any, Dict, List, Optional, Callable


class Condition:
    """A single weighted condition."""

    def __init__(self, field: str, op: str,
                 value: Any, weight: float = 1.0):
        self.field = field
        self.op = op
        self.value = value
        self.weight = weight

    def score(self, record: Dict) -> float:
        """Return score 0.0 to 1.0."""
        v = self._get(record, self.field)
        if v is None:
            return 0.0

        try:
            if self.op == "eq":
                return 1.0 if v == self.value else 0.0
            if self.op == "ne":
                return 1.0 if v != self.value else 0.0
            if self.op == "gt":
                return 1.0 if v > self.value else 0.0
            if self.op == "lt":
                return 1.0 if v < self.value else 0.0
            if self.op == "gte":
                return 1.0 if v >= self.value else 0.0
            if self.op == "lte":
                return 1.0 if v <= self.value else 0.0
            if self.op == "contains":
                return 1.0 if str(self.value) in str(v) else 0.0
            if self.op == "icontains":
                return 1.0 if str(self.value).lower() in str(v).lower() else 0.0
            if self.op == "between":
                lo, hi = self.value
                if lo <= v <= hi:
                    # Closer to middle = higher score
                    mid = (lo + hi) / 2
                    dist = abs(v - mid)
                    rng = (hi - lo) / 2
                    return 1.0 - (dist / rng) * 0.5 if rng > 0 else 1.0
                return 0.0
            if self.op == "near":
                # Numeric proximity — closer = higher
                if not isinstance(v, (int, float)):
                    return 0.0
                dist = abs(v - self.value)
                return 1.0 / (1.0 + dist)
        except (TypeError, AttributeError):
            return 0.0
        return 0.0

    @staticmethod
    def _get(record: Dict, path: str) -> Any:
        """Support nested fields: 'user.address.city'"""
        cur = record
        for p in path.split("."):
            if isinstance(cur, dict) and p in cur:
                cur = cur[p]
            else:
                return None
        return cur


class SuperpositionResult:
    """Result of superposition query."""

    def __init__(self, record: Dict, score: float,
                 details: List[Dict]):
        self.record = record
        self.score = score
        self.details = details

    def to_dict(self) -> Dict:
        return {
            "record": self.record,
            "score": round(self.score, 4),
            "details": self.details,
        }


class SuperpositionQuery:
    """
    Superposition query engine.

    Evaluate many conditions at once.
    Each record gets a score based on weighted match.
    """

    def __init__(self, records: List[Dict],
                 conditions: List[Condition],
                 combine: str = "weighted_sum"):
        self.records = records
        self.conditions = conditions
        self.combine = combine

    def evaluate(self, threshold: float = 0.0,
                 limit: int = None) -> List[SuperpositionResult]:
        """Run superposition and return ranked results."""
        results = []

        for rec in self.records:
            data = rec.get("data", rec)

            details = []
            total_weight = 0.0
            weighted_sum = 0.0

            for cond in self.conditions:
                s = cond.score(data)
                details.append({
                    "field": cond.field,
                    "op": cond.op,
                    "score": round(s, 3),
                    "weight": cond.weight,
                })
                weighted_sum += s * cond.weight
                total_weight += cond.weight

            if total_weight > 0:
                final = weighted_sum / total_weight
            else:
                final = 0.0

            if final >= threshold:
                results.append(
                    SuperpositionResult(rec, final, details)
                )

        # Sort by score, descending
        results.sort(key=lambda r: r.score, reverse=True)

        if limit:
            results = results[:limit]
        return results

    @staticmethod
    def intersect(results_a: List[SuperpositionResult],
                  results_b: List[SuperpositionResult]) -> List[SuperpositionResult]:
        """Intersection — records in both, scores multiplied."""
        map_a = {r.record.get("id", id(r.record)): r
                 for r in results_a}
        map_b = {r.record.get("id", id(r.record)): r
                 for r in results_b}

        common = set(map_a.keys()) & set(map_b.keys())
        merged = []
        for k in common:
            ra = map_a[k]
            rb = map_b[k]
            merged.append(SuperpositionResult(
                ra.record,
                ra.score * rb.score,
                ra.details + rb.details,
            ))
        merged.sort(key=lambda r: r.score, reverse=True)
        return merged

    @staticmethod
    def union(results_a: List[SuperpositionResult],
              results_b: List[SuperpositionResult]) -> List[SuperpositionResult]:
        """Union — records in either, scores combined."""
        map_a = {r.record.get("id", id(r.record)): r
                 for r in results_a}
        map_b = {r.record.get("id", id(r.record)): r
                 for r in results_b}

        all_keys = set(map_a.keys()) | set(map_b.keys())
        merged = []
        for k in all_keys:
            ra = map_a.get(k)
            rb = map_b.get(k)
            score = (ra.score if ra else 0) + (rb.score if rb else 0)
            record = ra.record if ra else rb.record
            details = (ra.details if ra else []) + (rb.details if rb else [])
            merged.append(SuperpositionResult(record, score, details))
        merged.sort(key=lambda r: r.score, reverse=True)
        return merged
