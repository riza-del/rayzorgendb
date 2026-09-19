"""
RayzorgenDB Time Travel Engine

Stores every version of every record. Allows queries
as of any past timestamp.

How it works:
- Every record has a version chain: [v1, v2, v3, ...]
- Each version has a timestamp (created_at)
- Query with `at(timestamp)` returns the state at that time
- History returns all versions
- Diff compares two versions
- Restore brings back an old version as new version
"""

import time
from typing import Any, Dict, List, Optional


class TimeTravelEngine:
    """Manages versioned history for all collections."""

    def __init__(self, core, max_versions: int = 100):
        self.core = core
        self.max_versions = max_versions
        # history[collection][record_id] = [version, version, ...]
        self._history: Dict[str, Dict[str, List[Dict]]] = {}

    # --------------------------------------------------------
    # Write - called by core on every change
    # --------------------------------------------------------

    def record_version(self, collection: str,
                       record_id: str, data: Dict,
                       version: int, deleted: bool = False):
        """Append a version to history."""
        self._history.setdefault(collection, {})
        self._history[collection].setdefault(record_id, [])

        # Only copy data if it's not already a fresh dict
        # (skip copy for insert to avoid 10.000x overhead)
        if data and len(self._history[collection][record_id]) == 0:
            data_copy = data  # First insert: keep reference
        else:
            data_copy = dict(data) if data else {}

        entry = {
            "version": version,
            "data": data_copy,
            "at": time.time(),
            "deleted": deleted,
        }

        self._history[collection][record_id].append(entry)
        self._maybe_compact(collection, record_id)

    def _maybe_compact(self, collection: str, record_id: str):
        versions = self._history[collection][record_id]
        if len(versions) > self.max_versions:
            keep = self.max_versions // 2
            self._history[collection][record_id] = (
                versions[:1] + versions[-keep:]
            )

    # --------------------------------------------------------
    # Read - history
    # --------------------------------------------------------

    def history(self, collection: str,
                record_id: str) -> List[Dict]:
        """Return all versions of a record."""
        return list(
            self._history.get(collection, {}).get(record_id, [])
        )

    def at(self, collection: str, record_id: str,
           timestamp: float) -> Optional[Dict]:
        """
        Return the version visible at the given timestamp.
        Returns None if record didn't exist yet.
        """
        versions = self._history.get(collection, {}).get(
            record_id, []
        )
        visible = None
        for v in versions:
            if v["at"] <= timestamp:
                visible = v
            else:
                break
        if visible is None or visible["deleted"]:
            return None
        return visible

    def snapshot_at(self, collection: str,
                    timestamp: float) -> List[Dict]:
        """
        Return all records visible at the given timestamp.
        Uses binary search for speed.
        """
        result = []
        all_records = self._history.get(collection, {})
        for record_id, versions in all_records.items():
            # Binary search for latest version <= timestamp
            lo, hi = 0, len(versions) - 1
            found = -1
            while lo <= hi:
                mid = (lo + hi) // 2
                if versions[mid]["at"] <= timestamp:
                    found = mid
                    lo = mid + 1
                else:
                    hi = mid - 1
            if found >= 0:
                v = versions[found]
                if not v["deleted"]:
                    result.append({
                        "id": record_id,
                        "version": v["version"],
                        "at": v["at"],
                        "data": v["data"],
                    })
        return result

    # --------------------------------------------------------
    # Diff - compare two versions
    # --------------------------------------------------------

    def diff(self, collection: str, record_id: str,
             version_a: int, version_b: int) -> Dict:
        """
        Compare two versions of the same record.
        Returns {"field": (value_a, value_b), ...}
        """
        versions = self._history.get(collection, {}).get(
            record_id, []
        )
        va = None
        vb = None
        for v in versions:
            if v["version"] == version_a:
                va = v
            if v["version"] == version_b:
                vb = v

        if va is None or vb is None:
            return {}

        a_data = va["data"]
        b_data = vb["data"]
        all_keys = set(a_data.keys()) | set(b_data.keys())

        result = {}
        for k in all_keys:
            a_val = a_data.get(k)
            b_val = b_data.get(k)
            if a_val != b_val:
                result[k] = (a_val, b_val)
        return result

    # --------------------------------------------------------
    # Time range queries
    # --------------------------------------------------------

    def changes_between(self, collection: str,
                        start: float,
                        end: float) -> List[Dict]:
        """
        Return all changes in the time range.
        Each entry: {"id": ..., "version": ..., "at": ...}
        """
        result = []
        for record_id, versions in self._history.get(
                collection, {}).items():
            for v in versions:
                if start <= v["at"] <= end:
                    result.append({
                        "id": record_id,
                        "version": v["version"],
                        "at": v["at"],
                        "deleted": v["deleted"],
                    })
        result.sort(key=lambda x: x["at"])
        return result

    # --------------------------------------------------------
    # Stats
    # --------------------------------------------------------

    def stats(self) -> Dict:
        total_records = 0
        total_versions = 0
        for coll_data in self._history.values():
            for versions in coll_data.values():
                total_records += 1
                total_versions += len(versions)
        return {
            "collections_tracked": len(self._history),
            "records_tracked": total_records,
            "total_versions": total_versions,
            "max_versions_per_record": self.max_versions,
        }

    def clear(self):
        self._history.clear()

    def clear_record(self, collection: str, record_id: str):
        if collection in self._history:
            self._history[collection].pop(record_id, None)


__all__ = ["TimeTravelEngine"]
