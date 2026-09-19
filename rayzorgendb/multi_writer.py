"""
RayzorgenDB Multi-Writer

Allow multiple writers with proper isolation.
Uses optimistic locking + version check + queue.
"""

import os
import time
import threading
import uuid
from typing import Any, Dict, List, Optional


class WriteLock:
    """Per-record write lock."""

    def __init__(self):
        self._locks: Dict[str, threading.Lock] = {}
        self._global = threading.RLock()

    def get(self, collection: str, record_id: str) -> threading.Lock:
        key = collection + ":" + record_id
        with self._global:
            if key not in self._locks:
                self._locks[key] = threading.Lock()
            return self._locks[key]

    def release_all(self):
        with self._global:
            self._locks.clear()


class OptimisticConflict(Exception):
    """Raised when version mismatch detected."""
    pass


class MultiWriter:
    """
    Multi-writer engine with optimistic concurrency.

    Features:
    - Per-record write lock
    - Version check (optimistic)
    - Write queue with retry
    - Conflict detection
    """

    def __init__(self, core, max_retries: int = 3):
        self.core = core
        self.max_retries = max_retries
        self.locks = WriteLock()
        self._lock = threading.RLock()
        self._stats = {
            "writes": 0,
            "conflicts": 0,
            "retries": 0,
            "successful": 0,
        }

    def insert(self, collection: str, data: Dict) -> Dict:
        """Insert with lock."""
        with self._lock:
            self._stats["writes"] += 1
        rec = self.core.insert(collection, data)
        self._stats["successful"] += 1
        return {
            "id": rec.id,
            "data": rec.data,
            "version": rec.version,
        }

    def update(self, collection: str, record_id: str,
               data: Dict,
               expected_version: int = None) -> Optional[Dict]:
        """
        Update with optimistic concurrency.
        If expected_version given, fails if version differs.
        Retry on conflict.
        """
        for attempt in range(self.max_retries):
            with self._lock:
                self._stats["writes"] += 1

            lock = self.locks.get(collection, record_id)
            with lock:
                current = self.core.get(collection, record_id)
                if current is None:
                    return None

                # Optimistic check
                if (expected_version is not None and
                        current.version != expected_version):
                    with self._lock:
                        self._stats["conflicts"] += 1
                    if attempt < self.max_retries - 1:
                        with self._lock:
                            self._stats["retries"] += 1
                        time.sleep(0.01 * (attempt + 1))
                        continue
                    raise OptimisticConflict(
                        "Version mismatch: expected " +
                        str(expected_version) + ", got " +
                        str(current.version)
                    )

                result = self.core.update(
                    collection, record_id, data
                )
                self._stats["successful"] += 1
                return {
                    "id": result.id,
                    "data": result.data,
                    "version": result.version,
                }

        return None

    def update_cas(self, collection: str, record_id: str,
                   data: Dict, expected_version: int) -> bool:
        """Compare-and-swap update. Returns success."""
        try:
            self.update(
                collection, record_id, data,
                expected_version=expected_version,
            )
            return True
        except OptimisticConflict:
            return False

    def delete(self, collection: str, record_id: str) -> bool:
        with self._lock:
            self._stats["writes"] += 1
        lock = self.locks.get(collection, record_id)
        with lock:
            result = self.core.delete(collection, record_id)
            if result:
                self._stats["successful"] += 1
            return result

    def stats(self) -> Dict:
        with self._lock:
            return dict(self._stats)


class WriterPool:
    """
    Pool of workers for parallel writes.
    Useful for bulk imports.
    """

    def __init__(self, core, n_workers: int = 4):
        self.core = core
        self.n_workers = n_workers
        self.mw = MultiWriter(core)
        self._lock = threading.RLock()
        self._stats = {
            "submitted": 0,
            "completed": 0,
            "errors": 0,
        }

    def parallel_insert(self, collection: str,
                        items: List[Dict]) -> List[str]:
        """Insert items in parallel."""
        results = []
        errors = []
        chunk_size = max(1, len(items) // self.n_workers)

        def worker(chunk):
            for item in chunk:
                try:
                    rec = self.mw.insert(collection, item)
                    with self._lock:
                        results.append(rec["id"])
                        self._stats["completed"] += 1
                except Exception as e:
                    with self._lock:
                        errors.append(str(e))
                        self._stats["errors"] += 1

        threads = []
        for i in range(0, len(items), chunk_size):
            chunk = items[i:i + chunk_size]
            with self._lock:
                self._stats["submitted"] += len(chunk)
            t = threading.Thread(
                target=worker, args=(chunk,)
            )
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        return results

    def stats(self) -> Dict:
        with self._lock:
            return {
                **self._stats,
                "workers": self.n_workers,
                "mw_stats": self.mw.stats(),
            }


__all__ = [
    "MultiWriter", "WriterPool",
    "OptimisticConflict", "WriteLock",
]
