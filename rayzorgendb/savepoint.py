"""
RayzorgenDB Savepoints

Nested transactions dengan savepoint.
"""

import time
import uuid
import threading
from typing import Any, Dict, List, Optional


class Savepoint:
    """A single savepoint in a transaction."""

    def __init__(self, name: str, snapshot: Dict):
        self.name = name
        self.snapshot = snapshot
        self.created_at = time.time()


class SavepointTransaction:
    """
    Transaction with savepoint support.

    Usage:
        tx = db.transaction_v2()
        tx.begin()
        tx.insert("users", {"nama": "A"})
        tx.savepoint("sp1")
        tx.insert("users", {"nama": "B"})
        tx.rollback_to("sp1")  # rollback B, keep A
        tx.commit()
    """

    def __init__(self, core):
        self.core = core
        self._ops: List = []
        self._savepoints: List[Savepoint] = []
        self._initial_snapshot: Optional[Dict] = None
        self._lock = threading.RLock()
        self.active = False

    def begin(self) -> "SavepointTransaction":
        with self._lock:
            self._initial_snapshot = self.core._snapshot()
            self.active = True
            self._ops.clear()
            self._savepoints.clear()
        return self

    def insert(self, collection: str, data: Dict):
        self._require_active()
        with self._lock:
            self._ops.append(
                ("insert", collection, {"data": data})
            )

    def update(self, collection: str, record_id: str, data: Dict):
        self._require_active()
        with self._lock:
            self._ops.append(
                ("update", collection,
                 {"id": record_id, "data": data})
            )

    def delete(self, collection: str, record_id: str):
        self._require_active()
        with self._lock:
            self._ops.append(
                ("delete", collection, {"id": record_id})
            )

    def savepoint(self, name: str):
        """Create a savepoint."""
        self._require_active()
        with self._lock:
            sp = Savepoint(
                name,
                {
                    "ops_count": len(self._ops),
                },
            )
            self._savepoints.append(sp)
        return name

    def rollback_to(self, name: str) -> bool:
        """Rollback to a savepoint. Keep ops before savepoint."""
        self._require_active()
        with self._lock:
            # Cari savepoint
            idx = -1
            for i, sp in enumerate(self._savepoints):
                if sp.name == name:
                    idx = i
                    break
            if idx < 0:
                return False

            sp = self._savepoints[idx]
            ops_count = sp.snapshot["ops_count"]

            # Buang ops setelah savepoint
            self._ops = self._ops[:ops_count]

            # Buang savepoint setelah ini (termasuk dirinya)
            self._savepoints = self._savepoints[:idx]
        return True

    def release_savepoint(self, name: str) -> bool:
        """Release a savepoint (tidak rollback)."""
        with self._lock:
            for i, sp in enumerate(self._savepoints):
                if sp.name == name:
                    self._savepoints.pop(i)
                    return True
        return False

    def commit(self) -> bool:
        self._require_active()
        with self._lock:
            try:
                for op, coll, payload in self._ops:
                    if op == "insert":
                        self.core._raw_insert(
                            coll, payload["data"]
                        )
                    elif op == "update":
                        self.core._raw_update(
                            coll, payload["id"],
                            payload["data"]
                        )
                    elif op == "delete":
                        self.core._raw_delete(
                            coll, payload["id"]
                        )
                self.core._flush_all()
                self._cleanup()
                return True
            except Exception:
                self.rollback()
                raise

    def rollback(self):
        if self._initial_snapshot is not None:
            self.core._restore_snapshot(
                self._initial_snapshot
            )
        self._cleanup()

    def _cleanup(self):
        self._ops.clear()
        self._savepoints.clear()
        self._initial_snapshot = None
        self.active = False

    def _require_active(self):
        if not self.active:
            raise RuntimeError("Transaction not active")

    def stats(self) -> Dict:
        return {
            "active": self.active,
            "operations": len(self._ops),
            "savepoints": [sp.name for sp in self._savepoints],
        }


__all__ = ["SavepointTransaction", "Savepoint"]
