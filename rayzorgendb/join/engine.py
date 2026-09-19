"""
RayzorgenDB JoinEngine — FIXED
- _field sekarang support top-level (id, version, dll)
- Right join fixed
"""

from typing import Any, Dict, List, Optional, Tuple, Callable


# ─── Field helper ────────────────────────────
def _extract(record: Dict, path: str) -> Any:
    """
    Ambil field dari record.
    Prioritas:
      1. Cek di dalam record["data"]
      2. Fallback ke top-level record (id, version, dll)
    Support nested: 'user.address.city'
    """
    if not path:
        return None
    
    # Prioritas 1: di dalam "data"
    data = record.get("data")
    if isinstance(data, dict):
        v = _walk(data, path)
        if v is not None:
            return v
    
    # Prioritas 2: top-level
    return _walk(record, path)


def _walk(obj: Any, path: str) -> Any:
    cur = obj
    for p in path.split("."):
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        else:
            return None
    return cur


def _to_public(rec: Dict) -> Dict:
    """Convert raw record ke public format"""
    return {
        "id": rec.get("id"),
        "data": rec.get("data", {}),
        "created_at": rec.get("created_at"),
        "updated_at": rec.get("updated_at"),
        "version": rec.get("version", 1),
    }


# ─── JoinQuery ───────────────────────────────
class JoinQuery:
    def __init__(self, rows: List[Dict],
                 collections: List[str]):
        self._rows = rows
        self._collections = collections
    
    def where(self, path: str, op: str, value: Any) -> "JoinQuery":
        self._rows = [
            r for r in self._rows
            if self._compare(self._get_path(r, path), op, value)
        ]
        return self
    
    def where_fn(self, fn: Callable) -> "JoinQuery":
        self._rows = [r for r in self._rows if fn(r)]
        return self
    
    def where_any(self, field: str, op: str,
                  value: Any) -> "JoinQuery":
        def matches(row):
            for data in row["_joined"].values():
                if isinstance(data, dict):
                    if self._compare(
                        _walk(data.get("data", {}), field),
                        op, value,
                    ):
                        return True
                    # Cek top-level juga
                    if self._compare(data.get(field), op, value):
                        return True
                elif isinstance(data, list):
                    for item in data:
                        if self._compare(
                            _walk(item.get("data", {}), field),
                            op, value,
                        ):
                            return True
            return False
        self._rows = [r for r in self._rows if matches(r)]
        return self
    
    def order_by(self, path: str,
                 desc: bool = False) -> "JoinQuery":
        def k(r):
            v = self._get_path(r, path)
            if v is None:
                return (1, "")
            return (0, v)
        try:
            self._rows.sort(key=k, reverse=desc)
        except TypeError:
            self._rows.sort(
                key=lambda r: str(k(r)), reverse=desc
            )
        return self
    
    def limit(self, n: int) -> "JoinQuery":
        if n > 0:
            self._rows = self._rows[:n]
        return self
    
    def skip(self, n: int) -> "JoinQuery":
        self._rows = self._rows[n:]
        return self
    
    def select(self, **aliases) -> "JoinQuery":
        new_rows = []
        for r in self._rows:
            new = {}
            for alias, path in aliases.items():
                new[alias] = self._get_path(r, path)
            new_rows.append(new)
        self._rows = new_rows
        return self
    
    def aggregate(self, path: str, op: str = "count") -> Any:
        values = []
        for r in self._rows:
            v = self._get_path(r, path)
            if isinstance(v, list):
                values.extend(
                    x for x in v
                    if isinstance(x, (int, float))
                    and not isinstance(x, bool)
                )
            elif isinstance(v, (int, float)) and not isinstance(v, bool):
                values.append(v)
        
        if op == "count":
            return len(self._rows)
        if not values:
            return 0 if op != "avg" else None
        
        op = op.lower()
        if op == "sum":   return sum(values)
        if op == "avg":   return sum(values) / len(values)
        if op == "min":   return min(values)
        if op == "max":   return max(values)
        return None
    
    def group_by(self, path: str,
                 agg_path: str = None,
                 agg_op: str = "count") -> Dict:
        groups: Dict[Any, List[Dict]] = {}
        for r in self._rows:
            key = self._get_path(r, path)
            if isinstance(key, (list, dict)):
                key = str(key)
            groups.setdefault(key, []).append(r)
        
        result = {}
        for k, rows in groups.items():
            if agg_path and agg_op != "count":
                vals = []
                for r in rows:
                    v = self._get_path(r, agg_path)
                    if isinstance(v, list):
                        vals.extend(
                            x for x in v
                            if isinstance(x, (int, float))
                            and not isinstance(x, bool)
                        )
                    elif isinstance(v, (int, float))                             and not isinstance(v, bool):
                        vals.append(v)
                if not vals:
                    result[k] = 0
                elif agg_op == "sum":
                    result[k] = sum(vals)
                elif agg_op == "avg":
                    result[k] = sum(vals) / len(vals)
                elif agg_op == "min":
                    result[k] = min(vals)
                elif agg_op == "max":
                    result[k] = max(vals)
                else:
                    result[k] = len(vals)
            else:
                result[k] = len(rows)
        return result
    
    def all(self) -> List[Dict]:
        return list(self._rows)
    
    def first(self) -> Optional[Dict]:
        return self._rows[0] if self._rows else None
    
    def count(self) -> int:
        return len(self._rows)
    
    # ─── Helpers ────────────────────────────────
    def _get_path(self, row: Dict, path: str) -> Any:
        """
        Ambil path dari row hasil join.
        Format:
          "users.name"           → data.name dari users
          "users.id"             → id users (top-level)
          "orders[].total"       → list total
          "orders.total"         → total pertama
        """
        if not path:
            return None
        
        array_mode = "[]" in path
        path_clean = path.replace("[]", "")
        parts = path_clean.split(".", 1)
        
        joined = row.get("_joined", row)
        if len(parts) == 1:
            return joined.get(parts[0])
        
        coll_name, rest = parts
        target = joined.get(coll_name)
        
        if target is None:
            return None
        
        if isinstance(target, list):
            if array_mode:
                return [
                    _extract(item, rest)
                    for item in target
                ]
            return _extract(target[0], rest) if target else None
        
        if isinstance(target, dict):
            return _extract(target, rest)
        
        return None
    
    @staticmethod
    def _compare(v, op, target):
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
            if op == "exists":     return (v is not None) == bool(target)
            if op == "between":
                lo, hi = target
                return v is not None and lo <= v <= hi
        except (TypeError, AttributeError):
            return False
        return False


# ─── JoinEngine ──────────────────────────────
class JoinEngine:
    def __init__(self, core):
        self.core = core
    
    def join(self, left_collection: str,
             right_collection: str,
             left_key: str,
             right_key: str,
             join_type: str = "left",
             as_: str = None) -> JoinQuery:
        join_type = join_type.lower()
        if join_type not in ("left", "inner", "right"):
            raise ValueError(
                "join_type harus 'left', 'inner', atau 'right'"
            )

        # Validate collections exist
        if left_collection not in self.core._data:
            raise KeyError(
                "Collection '" + left_collection +
                "' does not exist"
            )
        if right_collection not in self.core._data:
            raise KeyError(
                "Collection '" + right_collection +
                "' does not exist"
            )
        
        alias = as_ or right_collection
        
        left_data = list(
            self.core._data.get(left_collection, {}).values()
        )
        right_data = list(
            self.core._data.get(right_collection, {}).values()
        )
        
        # Index kanan by key
        right_index: Dict[Any, List[Dict]] = {}
        for rec in right_data:
            kv = _extract(rec, right_key)
            if kv is not None:
                right_index.setdefault(kv, []).append(rec)
        
        rows = []
        matched_right_ids = set()
        
        for lrec in left_data:
            lkey = _extract(lrec, left_key)
            matches = right_index.get(lkey, [])
            
            if join_type == "right" and not matches:
                continue
            
            right_items = [_to_public(m) for m in matches]
            
            for m in matches:
                matched_right_ids.add(m["id"])
            
            row = {
                "_joined": {
                    left_collection: _to_public(lrec),
                    alias: right_items,
                }
            }
            rows.append(row)
        
        # Right join: tambah yang kanan tidak match
        if join_type == "right":
            for rrec in right_data:
                if rrec["id"] not in matched_right_ids:
                    rows.append({
                        "_joined": {
                            left_collection: None,
                            alias: [_to_public(rrec)],
                        }
                    })
        
        # Inner join: buang yang kanan kosong
        if join_type == "inner":
            rows = [
                r for r in rows
                if r["_joined"].get(alias)
            ]
        
        return JoinQuery(rows, [left_collection, alias])
    
    def join_many(self, base_collection: str,
                  joins: List[Dict]) -> JoinQuery:
        if not joins:
            base_data = list(
                self.core._data.get(base_collection, {}).values()
            )
            rows = [
                {"_joined": {base_collection: _to_public(r)}}
                for r in base_data
            ]
            return JoinQuery(rows, [base_collection])
        
        first = joins[0]
        q = self.join(
            base_collection,
            first["collection"],
            first["left_key"],
            first["right_key"],
            first.get("type", "left"),
            first.get("as_"),
        )
        
        for j in joins[1:]:
            q = self._chain_join(q, j)
        
        return q
    
    def _chain_join(self, q: JoinQuery,
                    join_spec: Dict) -> JoinQuery:
        target_coll = join_spec["collection"]
        left_key = join_spec["left_key"]
        right_key = join_spec["right_key"]
        alias = join_spec.get("as_", target_coll)
        join_type = join_spec.get("type", "left")
        
        target_data = list(
            self.core._data.get(target_coll, {}).values()
        )
        
        t_index: Dict[Any, List[Dict]] = {}
        for rec in target_data:
            kv = _extract(rec, right_key)
            if kv is not None:
                t_index.setdefault(kv, []).append(rec)
        
        new_rows = []
        for row in q.all():
            # Ambil SEMUA nilai key dari source (bisa dari list)
            lvalues = self._extract_keys(row, left_key)
            
            # Kumpulkan semua produk yang match (dedup by id)
            seen_ids = set()
            matched_products = []
            for lv in lvalues:
                for m in t_index.get(lv, []):
                    if m["id"] not in seen_ids:
                        seen_ids.add(m["id"])
                        matched_products.append(_to_public(m))
            
            enriched = {**row["_joined"]}
            enriched[alias] = matched_products
            
            if join_type == "inner" and not matched_products:
                continue
            
            new_rows.append({"_joined": enriched})
        
        return JoinQuery(
            new_rows, list(q._collections) + [alias]
        )
    
    def _extract_keys(self, row: Dict, path: str) -> List[Any]:
        """
        Ambil SEMUA nilai key dari row.
        Kalau path menunjuk list, return semua nilai unik.
        Contoh: "orders.product_id" → [p1_id, p2_id]
        """
        joined = row["_joined"]
        
        if "." in path:
            coll, field = path.split(".", 1)
            target = joined.get(coll)
            if target is None:
                return []
            if isinstance(target, list):
                # Ambil dari SEMUA item di list
                values = []
                for item in target:
                    v = _extract(item, field)
                    if v is not None:
                        values.append(v)
                return list(set(values))  # unik
            if isinstance(target, dict):
                v = _extract(target, field)
                return [v] if v is not None else []
            return []
        
        # Path tanpa titik — cari di semua koleksi
        values = []
        for coll_name, data in joined.items():
            if isinstance(data, dict):
                v = _extract(data, path)
                if v is not None:
                    values.append(v)
            elif isinstance(data, list):
                for item in data:
                    v = _extract(item, path)
                    if v is not None:
                        values.append(v)
        return list(set(values))
    
    def _extract_key(self, row: Dict, path: str) -> Any:
        joined = row["_joined"]
        
        if "." in path:
            coll, field = path.split(".", 1)
            target = joined.get(coll)
            if target is None:
                return None
            if isinstance(target, list):
                if not target:
                    return None
                return _extract(target[0], field)
            if isinstance(target, dict):
                return _extract(target, field)
            return None
        
        for coll_name, data in joined.items():
            if isinstance(data, dict):
                v = _extract(data, path)
                if v is not None:
                    return v
            elif isinstance(data, list):
                for item in data:
                    v = _extract(item, path)
                    if v is not None:
                        return v
        return None
