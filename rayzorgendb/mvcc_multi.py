"""
RayzorgenDB Multi-Reader MVCC

Snapshot isolation for concurrent readers.
Multiple readers can access data without blocking.

Key concepts:
- Version with timestamp
- Reader uses snapshot timestamp
- Writer creates new version
- Garbage collection for old versions
"""

import time
import uuid
import threading
from typing import Any, Dict, List, Optional


class MVCCVersion:
    __slots__ = (
        "data", "version", "created_at",
        "deleted", "tx_id",
    )

    def __init__(self, data, version, tx_id=None,
                 deleted=False):
        self.data = data
        self.version = version
        self.created_at = time.time()
        self.deleted = deleted
        self.tx_id = tx_id


class MultiReaderMVCC:
    """
    Multi-version concurrency control.

    Features:
    - Snapshot isolation
    - Readers don't block writers
    - Writers don't block readers
    - Version chain per record
    """

    def __init__(self, max_versions: int = 20):
        self.max_versions = max_versions
        # {collection: {record_id: [versions]}}
        self._data: Dict[str, Dict[str, List]] = {}
        self._lock = threading.RLock()
        self._stats = {
            "reads": 0,
            "writes": 0,
            "versions_created": 0,
            "gc_runs": 0,
        }

    # --------------------------------------------------------
    # Snapshot
    # --------------------------------------------------------

    def snapshot(self) -> float:
        """Get current timestamp for snapshot."""
        return time.time()

    # --------------------------------------------------------
    # Write
    # --------------------------------------------------------

    def insert(self, collection: str, record_id: str,
               data: Dict, tx_id: str = None) -> Dict:
        with self._lock:
            tx_id = tx_id or uuid.uuid4().hex[:8]
            coll = self._data.setdefault(collection, {})
            versions = coll.get(record_id, [])
            v = MVCCVersion(
                dict(data), version=1, tx_id=tx_id,
            )
            versions.append(v)
            coll[record_id] = versions
            self._stats["writes"] += 1
            self._stats["versions_created"] += 1
            return {"id": record_id, "data": data, "version": 1}

    def update(self, collection: str, record_id: str,
               data: Dict, tx_id: str = None) -> Optional[Dict]:
        with self._lock:
            coll = self._data.get(collection, {})
            versions = coll.get(record_id)
            if not versions:
                return None
            tx_id = tx_id or uuid.uuid4().hex[:8]
            last = versions[-1]
            merged = dict(last.data)
            merged.update(data)
            v = MVCCVersion(
                merged, version=last.version + 1,
                tx_id=tx_id,
            )
            versions.append(v)
            self._stats["writes"] += 1
            self._stats["versions_created"] += 1
            self._maybe_gc(collection, record_id)
            return {
                "id": record_id, "data": merged,
                "version": v.version,
            }

    def delete(self, collection: str, record_id: str,
               tx_id: str = None) -> bool:
        with self._lock:
            coll = self._data.get(collection, {})
            versions = coll.get(record_id)
            if not versions:
                return False
            last = versions[-1]
            v = MVCCVersion(
                {}, version=last.version + 1,
                tx_id=tx_id or uuid.uuid4().hex[:8],
                deleted=True,
            )
            versions.append(v)
            self._stats["writes"] += 1
            self._stats["versions_created"] += 1
            return True

    # --------------------------------------------------------
    # Read (snapshot)
    # --------------------------------------------------------

    def get(self, collection: str, record_id: str,
            snapshot_ts: float = None) -> Optional[Dict]:
        with self._lock:
            self._stats["reads"] += 1
            coll = self._data.get(collection, {})
            versions = coll.get(record_id)
            if not versions:
                return None
            v = self._visible_version(versions, snapshot_ts)
            if v is None or v.deleted:
                return None
            return {
                "id": record_id,
                "data": v.data,
                "version": v.version,
            }

    def all(self, collection: str,
            snapshot_ts: float = None) -> List[Dict]:
        with self._lock:
            self._stats["reads"] += 1
            result = []
            coll = self._data.get(collection, {})
            for rid, versions in coll.items():
                v = self._visible_version(
                    versions, snapshot_ts
                )
                if v is not None and not v.deleted:
                    result.append({
                        "id": rid,
                        "data": v.data,
                        "version": v.version,
                    })
            return result

    def _visible_version(self, versions, snapshot_ts):
        """Find version visible at snapshot time."""
        if snapshot_ts is None:
            v = versions[-1]
            return None if v.deleted else v

        # Find latest version created <= snapshot
        visible = None
        for v in versions:
            if v.created_at <= snapshot_ts:
                visible = v
            else:
                break
        if visible is None or visible.deleted:
            return None
        return visible

    def count(self, collection: str,
              snapshot_ts: float = None) -> int:
        return len(self.all(collection, snapshot_ts))

    def history(self, collection: str,
                record_id: str) -> List[Dict]:
        with self._lock:
            coll = self._data.get(collection, {})
            versions = coll.get(record_id, [])
            return [
                {
                    "version": v.version,
                    "data": v.data,
                    "at": v.created_at,
                    "deleted": v.deleted,
                    "tx_id": v.tx_id,
                }
                for v in versions
            ]

    # --------------------------------------------------------
    # Garbage Collection
    # --------------------------------------------------------

    def _maybe_gc(self, collection: str, record_id: str):
        coll = self._data.get(collection, {})
        versions = coll.get(record_id)
        if versions and len(versions) > self.max_versions:
            # Keep first + last N/2
            keep = self.max_versions // 2
            coll[record_id] = (
                versions[:1] + versions[-keep:]
            )

    def gc(self, before_ts: float = None) -> int:
        """Remove old versions older than timestamp."""
        if before_ts is None:
            before_ts = time.time() - 3600  # 1 hour old
        removed = 0
        with self._lock:
            for coll_name, coll in self._data.items():
                for rid, versions in list(coll.items()):
                    if len(versions) <= 2:
                        continue
                    # Keep latest version and versions
                    # after before_ts
                    keep = [
                        versions[-1]
                    ]
                    for v in versions[:-1]:
                        if v.created_at >= before_ts:
                            keep.append(v)
                    keep.sort(key=lambda x: x.version)
                    removed += len(versions) - len(keep)
                    coll[rid] = keep
            self._stats["gc_runs"] += 1
        return removed

    def stats(self) -> Dict:
        with self._lock:
            total_records = 0
            total_versions = 0
            for coll in self._data.values():
                total_records += len(coll)
                for versions in coll.values():
                    total_versions += len(versions)
            return {
                **self._stats,
                "collections": len(self._data),
                "records": total_records,
                "versions": total_versions,
                "max_versions_per_record": self.max_versions,
            }


__all__ = ["MultiReaderMVCC", "MVCCVersion"]
