"""
RayzorgenDB Integrity

Checksum per record, verify, detect corruption.
Uses CRC32 (fast) + optional SHA-256 (strong).
"""

import hashlib
import zlib
import json
import threading
from typing import Any, Dict, List, Tuple


def crc32(data: bytes) -> int:
    """Fast CRC32 checksum."""
    return zlib.crc32(data) & 0xFFFFFFFF


def sha256_short(data: bytes) -> str:
    """Short SHA-256 (16 hex chars)."""
    return hashlib.sha256(data).hexdigest()[:16]


class IntegrityManager:
    """Verify record integrity."""

    def __init__(self, algorithm: str = "crc32"):
        self.algorithm = algorithm
        self._lock = threading.RLock()
        self._stats = {
            "checked": 0,
            "passed": 0,
            "failed": 0,
        }

    def compute(self, data: Dict) -> str:
        """Compute checksum for a record."""
        text = json.dumps(
            data, sort_keys=True, default=str
        ).encode("utf-8")
        if self.algorithm == "sha256":
            return sha256_short(text)
        return str(crc32(text))

    def verify(self, data: Dict, expected: str) -> bool:
        """Verify record matches expected checksum."""
        with self._lock:
            self._stats["checked"] += 1
            actual = self.compute(data)
            if str(actual) == str(expected):
                self._stats["passed"] += 1
                return True
            self._stats["failed"] += 1
            return False

    def verify_batch(self, items: List[Tuple[Dict, str]]) -> Dict:
        """Verify many records. Returns summary."""
        passed = 0
        failed = 0
        corrupt = []

        for i, (data, expected) in enumerate(items):
            if self.verify(data, expected):
                passed += 1
            else:
                failed += 1
                corrupt.append(i)

        return {
            "total": len(items),
            "passed": passed,
            "failed": failed,
            "corrupt_indices": corrupt,
        }

    def stats(self) -> Dict:
        with self._lock:
            total = self._stats["checked"]
            ratio = (
                self._stats["passed"] / total
                if total > 0 else 0
            )
            return {
                **self._stats,
                "algorithm": self.algorithm,
                "integrity_ratio": round(ratio, 4),
            }


class IntegrityChecker:
    """Scan collections for corruption."""

    def __init__(self, db, manager: IntegrityManager = None):
        self.db = db
        self.manager = manager or IntegrityManager()
        self._lock = threading.RLock()
        self._checksums: Dict[str, Dict[str, str]] = {}

    def register(self, collection: str, record_id: str, data: Dict):
        """Register checksum for a record."""
        with self._lock:
            self._checksums.setdefault(collection, {})
            self._checksums[collection][record_id] = (
                self.manager.compute(data)
            )

    def check(self, collection: str) -> Dict:
        """Check all records in collection."""
        with self._lock:
            checksums = self._checksums.get(collection, {})
            if not checksums:
                return {
                    "collection": collection,
                    "total": 0,
                    "message": "no checksums registered",
                }

            coll = self.db.collection(collection)
            passed = 0
            failed = 0
            missing = 0
            corrupt_ids = []

            for rid, expected in checksums.items():
                rec = coll.get(rid)
                if rec is None:
                    missing += 1
                    continue
                if self.manager.verify(rec.data, expected):
                    passed += 1
                else:
                    failed += 1
                    corrupt_ids.append(rid)

            return {
                "collection": collection,
                "total": len(checksums),
                "passed": passed,
                "failed": failed,
                "missing": missing,
                "corrupt_ids": corrupt_ids,
            }

    def unregister(self, collection: str, record_id: str):
        with self._lock:
            if collection in self._checksums:
                self._checksums[collection].pop(record_id, None)

    def stats(self) -> Dict:
        with self._lock:
            total = sum(
                len(c) for c in self._checksums.values()
            )
            return {
                "collections": len(self._checksums),
                "records_tracked": total,
                "checksum_stats": self.manager.stats(),
            }


__all__ = [
    "IntegrityManager", "IntegrityChecker",
    "crc32", "sha256_short",
]
