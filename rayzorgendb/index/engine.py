"""
RayzorgenDB Index Engine
Index hash sederhana + prefix search.
"""

from typing import Any, Dict, List
from rayzorgendb.btree.tree import BTree


class Index:
    """
    Index satu field.
    Pakai set untuk O(1) insert/remove, bukan O(n).
    """
    
    def __init__(self, field: str):
        self.field = field
        # Set[str] instead of List[str] for O(1) membership
        self.map: Dict[Any, set] = {}
    
    def add(self, value: Any, record_id: str):
        key = self._key(value)
        bucket = self.map.get(key)
        if bucket is None:
            bucket = set()
            self.map[key] = bucket
        bucket.add(record_id)  # O(1)
    
    def remove(self, value: Any, record_id: str):
        key = self._key(value)
        bucket = self.map.get(key)
        if bucket is not None:
            bucket.discard(record_id)  # O(1)
            if not bucket:
                del self.map[key]
    
    def search(self, value: Any) -> List[str]:
        bucket = self.map.get(self._key(value))
        return list(bucket) if bucket else []
    
    def search_prefix(self, prefix: str) -> List[str]:
        p = str(prefix)
        out = set()
        for k, ids in self.map.items():
            if str(k).startswith(p):
                out.update(ids)
        return list(out)
    
    def clear(self):
        self.map.clear()
    
    @staticmethod
    def _key(value: Any) -> Any:
        if isinstance(value, (list, dict, set)):
            return str(sorted(value) if isinstance(value, set)
                       else value)
        return value


class IndexManager:
    """Kumpulan index per koleksi"""
    
    def __init__(self):
        self._indexes: Dict[str, Dict[str, Index]] = {}
        self._sorted: Dict[str, Dict[str, BTree]] = {}
    
    def create(self, collection: str, field: str) -> Index:
        self._indexes.setdefault(collection, {})
        if field not in self._indexes[collection]:
            self._indexes[collection][field] = Index(field)
        return self._indexes[collection][field]
    
    def drop(self, collection: str, field: str) -> bool:
        if collection in self._indexes:
            return self._indexes[collection].pop(field, None) is not None
        return False
    
    def drop_all(self, collection: str):
        self._indexes.pop(collection, None)
    
    def index_record(self, collection: str, record_id: str,
                     data: Dict):
        for field, idx in self._indexes.get(collection, {}).items():
            if field in data:
                idx.add(data[field], record_id)
    
    def unindex_record(self, collection: str, record_id: str,
                       data: Dict):
        for field, idx in self._indexes.get(collection, {}).items():
            if field in data:
                idx.remove(data[field], record_id)
    
    def rebuild(self, collection: str,
                records: Dict[str, Dict]):
        """Rebuild semua index. B+ Tree pakai bulk_load (cepat)."""
        # Hash indexes: clear + isi ulang
        for idx in self._indexes.get(collection, {}).values():
            idx.clear()
        for rid, raw in records.items():
            self.index_record(
                collection, rid, raw.get("data", {})
            )

        # B+ Tree: pakai bulk_load
        for field, tree in self._sorted.get(
                collection, {}).items():
            items = []
            for rid, raw in records.items():
                v = raw.get("data", {}).get(field)
                if v is not None:
                    try:
                        items.append((v, rid))
                    except Exception:
                        pass
            if items:
                try:
                    tree.bulk_load(items)
                except Exception:
                    pass
    
    def search(self, collection: str, field: str,
               value: Any) -> List[str]:
        idx = self._indexes.get(collection, {}).get(field)
        return idx.search(value) if idx else []
    
    def search_prefix(self, collection: str, field: str,
                      prefix: str) -> List[str]:
        idx = self._indexes.get(collection, {}).get(field)
        return idx.search_prefix(prefix) if idx else []
    
    def list_indexes(self, collection: str) -> List[str]:
        return list(self._indexes.get(collection, {}).keys())

    # --------------------------------------------------------
    # B+ Tree (sorted) index for range queries
    # --------------------------------------------------------

    def create_sorted(self, collection: str, field: str):
        self._sorted.setdefault(collection, {})
        if field not in self._sorted[collection]:
            self._sorted[collection][field] = BTree(order=8)

    def drop_sorted(self, collection: str, field: str) -> bool:
        if collection in self._sorted:
            return self._sorted[collection].pop(field, None) is not None
        return False

    def index_record_sorted(self, collection: str,
                            record_id: str, data: Dict):
        for field, tree in self._sorted.get(collection, {}).items():
            if field in data and data[field] is not None:
                try:
                    tree.insert(data[field], record_id)
                except TypeError:
                    pass

    def unindex_record_sorted(self, collection: str,
                              record_id: str, data: Dict):
        for field, tree in self._sorted.get(collection, {}).items():
            if field in data and data[field] is not None:
                try:
                    tree.delete(data[field], record_id)
                except TypeError:
                    pass

    def range_search(self, collection: str, field: str,
                     start=None, end=None) -> List[str]:
        tree = self._sorted.get(collection, {}).get(field)
        if tree is None:
            return []
        items = tree.range(start, end)
        # Set untuk dedup O(1), bukan list O(n)
        seen = set()
        for _, rid in items:
            seen.add(rid)
        return list(seen)

    def list_sorted_indexes(self, collection: str) -> List[str]:
        return list(self._sorted.get(collection, {}).keys())
