"""
RayzorgenDB Query Builder — FIXED
Field lookup otomatis masuk ke dalam 'data'.
"""

import re
from typing import Any, Dict, List, Callable, Optional


VALID_OPERATORS = {
    'eq', 'ne', 'gt', 'lt', 'gte', 'lte',
    'in', 'nin', 'contains', 'icontains',
    'startswith', 'endswith', 'regex',
    'exists', 'between',
}


class Query:
    """Chainable query"""
    
    def __init__(self, records: List[Dict]):
        self._records = list(records)
    
    def where(self, field: str, op: str, value: Any) -> "Query":
        if op not in VALID_OPERATORS:
            raise ValueError(
                "Unknown operator: '" + op + "'. "
                "Valid: " + ", ".join(sorted(VALID_OPERATORS))
            )
        self._records = [
            r for r in self._records
            if self._compare(self._get_field(r, field), op, value)
        ]
        return self
    
    def where_fn(self, fn: Callable[[Dict], bool]) -> "Query":
        self._records = [r for r in self._records if fn(r)]
        return self
    
    def order_by(self, field: str, desc: bool = False) -> "Query":
        def k(r):
            v = self._get_field(r, field)
            if v is None:
                return (1, "")
            return (0, v)
        try:
            self._records.sort(key=k, reverse=desc)
        except TypeError:
            self._records.sort(
                key=lambda r: (str(type(k(r))), str(k(r))),
                reverse=desc,
            )
        return self
    
    def limit(self, n: int) -> "Query":
        if n > 0:
            self._records = self._records[:n]
        return self
    
    def skip(self, n: int) -> "Query":
        self._records = self._records[n:]
        return self
    
    def select(self, *fields: str) -> "Query":
        """
        Ambil hanya field tertentu.
        Hasil tetap berbentuk record utuh {id, data, ...}
        tapi 'data' hanya berisi field yang dipilih.
        """
        new_records = []
        for r in self._records:
            new = dict(r)
            new["data"] = {
                f: self._get_field(r, f) for f in fields
            }
            new_records.append(new)
        self._records = new_records
        return self
    
    def all(self) -> List[Dict]:
        return list(self._records)
    
    def first(self) -> Optional[Dict]:
        return self._records[0] if self._records else None
    
    def last(self) -> Optional[Dict]:
        return self._records[-1] if self._records else None
    
    def count(self) -> int:
        return len(self._records)
    
    def pluck(self, field: str) -> List[Any]:
        return [self._get_field(r, field) for r in self._records]
    
    # ─── Internal ───────────────────────────────
    @staticmethod
    def _get_field(record: Dict, path: str) -> Any:
        """
        Ambil field dari record.
        Otomatis cek di dalam 'data' kalau tidak ada di top-level.
        Support nested: 'user.name' atau 'data.user.name'
        """
        if not path:
            return None
        
        # Prioritas 1: cek di dalam 'data'
        data = record.get("data")
        if isinstance(data, dict):
            v = Query._walk(data, path)
            if v is not None:
                return v
        
        # Prioritas 2: cek di top-level (id, version, dll)
        v = Query._walk(record, path)
        if v is not None:
            return v
        
        # Prioritas 3: coba dengan prefix 'data.'
        if path.startswith("data."):
            return Query._walk(record, path)
        
        return None
    
    @staticmethod
    def _walk(obj: Any, path: str) -> Any:
        cur = obj
        for p in path.split("."):
            if isinstance(cur, dict) and p in cur:
                cur = cur[p]
            else:
                return None
        return cur
    
    @staticmethod
    def _compare(v: Any, op: str, target: Any) -> bool:
        try:
            if op == "eq":         return v == target
            if op == "ne":         return v != target
            if op == "gt":         return v is not None and v > target
            if op == "lt":         return v is not None and v < target
            if op == "gte":        return v is not None and v >= target
            if op == "lte":        return v is not None and v <= target
            if op == "in":         return v in target
            if op == "nin":        return v not in target
            if op == "contains":   return str(target) in str(v)
            if op == "icontains":
                return str(target).lower() in str(v).lower()
            if op == "startswith":
                return str(v).startswith(str(target))
            if op == "endswith":
                return str(v).endswith(str(target))
            if op == "regex":
                return bool(re.search(str(target), str(v)))
            if op == "exists":     return (v is not None) == bool(target)
            if op == "between":
                lo, hi = target
                return v is not None and lo <= v <= hi
        except (TypeError, AttributeError, re.error):
            return False
        return False
