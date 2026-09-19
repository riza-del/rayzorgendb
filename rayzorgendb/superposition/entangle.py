"""
RayzorgenDB Entanglement

Declare that a field in one collection depends on
fields in another. When source changes, target is
invalidated and recalculated on read.

Inspired by reactive programming, materialized views,
and functional dependency graphs.
"""

import time
import threading
from typing import Any, Callable, Dict, List, Tuple


class Entanglement:
    """
    A single entanglement link.

    Example:
        entangle(
            source=("orders", "user_id"),
            target=("users", "total_orders"),
            compute=lambda orders: len(orders),
        )
    """

    def __init__(self, source_coll: str, source_field: str,
                 target_coll: str, target_field: str,
                 compute: Callable, match_on: str):
        self.source_coll = source_coll
        self.source_field = source_field
        self.target_coll = target_coll
        self.target_field = target_field
        self.compute = compute
        self.match_on = match_on
        self._cache: Dict[str, Any] = {}
        self._invalidated: set = set()
        self._lock = threading.RLock()

    def key(self) -> str:
        return "{}:{}:{}".format(
            self.source_coll, self.target_coll,
            self.target_field,
        )

    def invalidate(self, target_id: str):
        """Mark a target as needing recompute."""
        with self._lock:
            self._invalidated.add(target_id)
            self._cache.pop(target_id, None)

    def invalidate_all(self):
        with self._lock:
            self._invalidated.clear()
            self._cache.clear()

    def get(self, target_id: str, records_fn) -> Any:
        """Get computed value, recompute if invalidated."""
        with self._lock:
            if target_id in self._cache and                target_id not in self._invalidated:
                return self._cache[target_id]

            # Recompute
            value = self.compute(records_fn(target_id))
            self._cache[target_id] = value
            self._invalidated.discard(target_id)
            return value

    def stats(self) -> Dict:
        with self._lock:
            return {
                "cached": len(self._cache),
                "invalidated": len(self._invalidated),
                "link": self.key(),
            }


class EntanglementEngine:
    """
    Manages all entanglements.

    Hooks into CDC: when a write happens, invalidate
    affected targets.
    """

    def __init__(self, db):
        self.db = db
        self._links: List[Entanglement] = []
        self._lock = threading.RLock()
        self._stats = {
            "invalidations": 0,
            "recomputes": 0,
        }

    def entangle(self, source: Tuple[str, str],
                 target: Tuple[str, str],
                 compute: Callable,
                 match_on: str = "id") -> Entanglement:
        """
        Create an entanglement link.

        source: (collection, field_to_match_source)
        target: (collection, field_to_store_result)
        compute: function that takes list of source records
        match_on: field on target used to match source
        """
        source_coll, source_field = source
        target_coll, target_field = target

        link = Entanglement(
            source_coll, source_field,
            target_coll, target_field,
            compute, match_on,
        )
        with self._lock:
            self._links.append(link)

        return link

    def invalidate_for(self, collection: str,
                        record: Dict):
        """
        Called when a record changes.
        Invalidate any targets that depend on this collection.
        """
        with self._lock:
            links = [l for l in self._links
                     if l.source_coll == collection]

        for link in links:
            # Find targets that match
            try:
                target_coll = self.db.collection(
                    link.target_coll
                )
                # Invalidate all targets that reference this source
                for target_rec in target_coll.all():
                    # Check if this target uses this source
                    match_value = target_rec.data.get(
                        link.match_on
                    )
                    source_value = record.get(
                        link.source_field
                    )
                    if match_value == source_value:
                        link.invalidate(target_rec.id)
                        with self._lock:
                            self._stats["invalidations"] += 1
            except Exception:
                pass

    def get_entangled(self, collection: str,
                       record: Dict) -> Dict:
        """Get all entangled field values for a record."""
        result = {}
        with self._lock:
            links = [l for l in self._links
                     if l.target_coll == collection]

        for link in links:
            try:
                source_coll = self.db.collection(
                    link.source_coll
                )
                source_value = record.get(link.match_on)

                def fetch_sources(tid):
                    return [
                        s.to_dict() for s in source_coll.all()
                        if s.data.get(link.source_field) == source_value
                    ]

                value = link.get(record.get("id", "?"),
                                  fetch_sources)
                result[link.target_field] = value
                with self._lock:
                    self._stats["recomputes"] += 1
            except Exception:
                result[link.target_field] = None

        return result

    def stats(self) -> Dict:
        with self._lock:
            return {
                **self._stats,
                "links": len(self._links),
                "per_link": [l.stats() for l in self._links],
            }
