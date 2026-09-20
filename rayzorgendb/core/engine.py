"""
RayzorgenDB Core Engine
Enterprise-grade storage with WAL, binary codec, and multi-model support.
"""

import time
import uuid
import json
import threading
from typing import Any, Dict, List, Optional, Callable

from rayzorgendb.storage.binary_store import BinaryStore
from rayzorgendb.storage.wal.log import WAL
from rayzorgendb.index.engine import IndexManager
from rayzorgendb.join.engine import JoinEngine
from rayzorgendb.query.builder import Query
from rayzorgendb.config import DEFAULT_CONFIG
from rayzorgendb.lock.manager import LockManager
from rayzorgendb.cache.lru import LRUCache, QueryCache
from rayzorgendb.timetravel.engine import TimeTravelEngine
from rayzorgendb.stability import (
    intern_value, RAMMonitor, auto_choose_mode,
)
from rayzorgendb.metrics.collector import GLOBAL as _METRICS
from rayzorgendb.integrity import IntegrityManager as _Integrity


# ============================================================
# Record
# ============================================================

class Record:
    """A single record in the database."""

    __slots__ = ("id", "data", "created_at", "updated_at", "version")

    def __init__(self, data: Dict, record_id: str = None):
        self.id = record_id or uuid.uuid4().hex
        self.data = dict(data)
        now = time.time()
        self.created_at = now
        self.updated_at = now
        self.version = 1

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "data": self.data,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "Record":
        r = cls(d.get("data", {}), d.get("id"))
        r.created_at = d.get("created_at", time.time())
        r.updated_at = d.get("updated_at", r.created_at)
        r.version = d.get("version", 1)
        return r

    def __repr__(self):
        return "<Record id={} data={}>".format(
            self.id[:8], self.data
        )


# ============================================================
# Event Bus
# ============================================================

class EventBus:
    """Simple pub/sub for database events."""

    def __init__(self):
        self._subscribers: Dict[str, List[Callable]] = {}
        self._lock = threading.RLock()

    def on(self, event: str, handler: Callable):
        with self._lock:
            self._subscribers.setdefault(event, []).append(handler)

    def off(self, event: str, handler: Callable = None):
        with self._lock:
            if handler is None:
                self._subscribers.pop(event, None)
            else:
                try:
                    self._subscribers[event].remove(handler)
                except (KeyError, ValueError):
                    pass

    def emit(self, event: str, payload: Any):
        with self._lock:
            handlers = list(self._subscribers.get(event, []))
        for h in handlers:
            try:
                h(payload)
            except Exception:
                pass


# ============================================================
# Transaction
# ============================================================

class Transaction:
    """Atomic transaction with commit/rollback support."""

    def __init__(self, core: "RayzorgenCore"):
        self.core = core
        self._operations: List = []
        self._snapshot: Optional[Dict] = None
        self.active = False

    def begin(self) -> "Transaction":
        self._snapshot = self.core._snapshot()
        self.active = True
        return self

    def insert(self, collection: str, data: Dict):
        self._require_active()
        self._operations.append(
            ("insert", collection, {"data": data})
        )

    def update(self, collection: str, record_id: str, data: Dict):
        self._require_active()
        self._operations.append(
            ("update", collection,
             {"id": record_id, "data": data})
        )

    def delete(self, collection: str, record_id: str):
        self._require_active()
        self._operations.append(
            ("delete", collection, {"id": record_id})
        )

    def commit(self) -> bool:
        self._require_active()
        try:
            for op, coll, payload in self._operations:
                if op == "insert":
                    self.core._raw_insert(coll, payload["data"])
                elif op == "update":
                    self.core._raw_update(
                        coll, payload["id"], payload["data"]
                    )
                elif op == "delete":
                    self.core._raw_delete(coll, payload["id"])
            self.core._flush_all()
            self._cleanup()
            return True
        except Exception:
            self.rollback()
            raise

    def rollback(self):
        if self._snapshot is not None:
            self.core._restore_snapshot(self._snapshot)
        self._cleanup()

    def _cleanup(self):
        self._operations.clear()
        self._snapshot = None
        self.active = False

    def _require_active(self):
        if not self.active:
            raise RuntimeError("Transaction has not begun")


# ============================================================
# Core Engine
# ============================================================

class RayzorgenCore:
    """Main database engine."""

    def __init__(self, config=None):
        self.config = config or DEFAULT_CONFIG
        self.storage = BinaryStore(self.config.DATA_DIR)
        self.indexes = IndexManager()
        self.events = EventBus()
        self.join_engine = JoinEngine(self)
        self._lock = threading.RLock()
        self.locks = LockManager(
            self.config.DATA_DIR,
            timeout=getattr(
                self.config, 'LOCK_TIMEOUT', 30
            ),
        )
        self._data: Dict[str, Dict[str, Dict]] = {}
        self._stats = {
            "reads": 0,
            "writes": 0,
            "deletes": 0,
            "queries": 0,
            "transactions": 0,
            "errors": 0,
            "wal_appends": 0,
            "snapshots": 0,
        }
        self._started = time.time()
        self._batch_mode = False
        self._turbo_mode = False
        self._wal_only = False
        self._is_large = getattr(
            self.config, 'MODE', 'full'
        ) == 'large'
        self.timetravel = TimeTravelEngine(self)

        # === AUTO-INTEGRATED MODULES ===
        # Metrics: track every operation
        self._metrics = _METRICS
        self._integrity = _Integrity()
        self._schema = None        # set via set_schema()
        self._optimizer = None     # set via analyze()
        self._logger = None        # set via enable_logging()
        self._multi_writer = None  # set via enable_multi_writer()
        # CDC stream untuk replication
        try:
            from rayzorgendb.cdc import CDCStream
            self.cdc_stream = CDCStream()
        except ImportError:
            self.cdc_stream = None
        self._ram_monitor = RAMMonitor(
            min_free_mb=200.0, check_every=5000
        )
        # Auto-adjust mode if not set explicitly
        if getattr(self.config, 'MODE', 'full') == 'auto':
            detected = auto_choose_mode()
            self.config.MODE = detected
            self._is_large = detected == 'large'
        _cache_size = 100 if getattr(
            self.config, 'MODE', 'full'
        ) == 'large' else 5000
        self.record_cache = LRUCache(
            max_size=_cache_size, default_ttl=None
        )
        self.query_cache = QueryCache(
            max_size=500, ttl=60.0
        )
        self._load_all()

    # --------------------------------------------------------
    # Persistence
    # --------------------------------------------------------

    def _load_all(self):
        for name in self.storage.list_collections():
            try:
                lock = self.locks.collection_lock(name)
                lock.acquire(timeout=5)
                try:
                    self._data[name] = self.storage.load(name)
                finally:
                    lock.release()
            except Exception:
                self._data[name] = {}
                self._stats["errors"] += 1

    def _flush_all(self):
        for name, records in list(self._data.items()):
            self.storage.save(name, records)
            self._stats["snapshots"] += 1

    WAL_SNAPSHOT_THRESHOLD = 1024 * 1024  # 1 MB

    def _flush_one(self, collection: str):
        if collection not in self._data:
            return
        if self._wal_only:
            return

        # Snapshot hanya kalau WAL sudah besar
        try:
            wal_size = self.storage.wal_size(collection)
        except Exception:
            wal_size = 0
        if wal_size < self.WAL_SNAPSHOT_THRESHOLD:
            return  # cukup WAL saja

        lock = self.locks.collection_lock(collection)
        try:
            lock.acquire(timeout=self.locks.timeout)
            self._merge_from_disk(collection)
            self.storage.save(
                collection, self._data[collection]
            )
            self._stats["snapshots"] += 1
        except Exception:
            self._stats["errors"] += 1
        finally:
            try:
                lock.release()
            except Exception:
                pass

    def set_wal_only(self, enabled: bool):
        """Enable WAL-only mode (fast writes, no snapshot)."""
        self._wal_only = enabled

    def force_snapshot(self):
        """Force snapshot of all collections."""
        self._flush_all()

    def _merge_from_disk(self, collection: str):
        """Merge on-disk changes from other processes."""
        try:
            disk = self.storage.load(collection)
        except Exception:
            return
        if not isinstance(disk, dict):
            return
        in_memory = self._data.get(collection, {})
        # Disk has records we don't know about
        for rid, raw in disk.items():
            if rid not in in_memory:
                in_memory[rid] = raw

    # --------------------------------------------------------
    # Collection Management
    # --------------------------------------------------------

    def create_collection(self, name: str) -> bool:
        with self._lock:
            if name in self._data:
                return False
            self._data[name] = {}
            self._flush_one(name)
            self.events.emit("collection.created", {"name": name})
            return True

    def drop_collection(self, name: str) -> bool:
        with self._lock:
            if name not in self._data:
                return False
            del self._data[name]
            self.indexes.drop_all(name)
            self.storage.delete(name)
            self.events.emit("collection.dropped", {"name": name})
            return True

    def list_collections(self) -> List[str]:
        with self._lock:
            return list(self._data.keys())

    def has_collection(self, name: str) -> bool:
        return name in self._data

    # --------------------------------------------------------
    # CRUD Operations
    # --------------------------------------------------------

    def insert(self, collection: str, data: Dict) -> Record:
        with self._lock:
            record = self._raw_insert(collection, data)
            if not self._batch_mode:
                self._flush_one(collection)
            return record

    def _raw_insert(self, collection: str, data: Dict) -> Record:
        self._ensure(collection)
        if not isinstance(data, dict):
            raise TypeError("data must be a dict")

        # TURBO MODE: minimal work, maximum speed
        if self._turbo_mode:
            record = Record(data)
            raw = record.to_dict()
            self._data[collection][record.id] = raw
            self.storage.append_wal(
                collection, WAL.OP_INSERT, record.id, raw
            )
            self._stats["wal_appends"] += 1
            self._stats["writes"] += 1
            return record

        # Normal mode: semua tracking
        try:
            self._ram_monitor.check()
        except AttributeError:
            pass
        if not self._is_large:
            data = intern_value(data)
        record = Record(data)
        raw = record.to_dict()
        self._data[collection][record.id] = raw
        self.storage.append_wal(
            collection, WAL.OP_INSERT, record.id, raw
        )
        self._stats["wal_appends"] += 1
        self.indexes.index_record(
            collection, record.id, record.data
        )
        self.indexes.index_record_sorted(
            collection, record.id, record.data
        )
        self._stats["writes"] += 1
        self.record_cache.set(
            collection + ":" + record.id, raw
        )
        self.query_cache.invalidate_collection(collection)
        self.events.emit("record.inserted", {
            "collection": collection,
            "id": record.id,
            "data": record.data,
        })
        if getattr(self, "cdc_stream", None):
            self.cdc_stream.emit(
                "insert", collection, record.id,
                data=record.data,
            )
        # === AUTO: metrics + integrity + schema ===
        try:
            self._metrics.increment("inserts")
            self._metrics.record("insert", 0.1)
        except Exception:
            pass
        try:
            if getattr(self, "_schema", None) is not None:
                self._schema.validate(record.data)
        except Exception:
            pass
        return record

    def get_many_raw(self, collection: str,
                     ids: List[str]) -> List[Dict]:
        """Fast bulk get - returns raw dicts, no Record wrapper."""
        coll = self._data.get(collection, {})
        result = []
        for rid in ids:
            raw = coll.get(rid)
            if raw is not None:
                result.append(raw)
        return result

    def find_by_index_raw(self, collection: str, field: str,
                          value: Any) -> List[Dict]:
        """Fast index lookup - no Record wrapper."""
        ids = self.indexes.search(collection, field, value)
        coll = self._data.get(collection, {})
        return [coll[i] for i in ids if i in coll]

    def range_raw(self, collection: str, field: str,
                  start=None, end=None) -> List[Dict]:
        """Fast range query - no Record wrapper."""
        ids = self.indexes.range_search(
            collection, field, start, end
        )
        coll = self._data.get(collection, {})
        return [coll[i] for i in ids if i in coll]

    def get(self, collection: str,
            record_id: str) -> Optional[Record]:
        with self._lock:
            self._stats["reads"] += 1
            cache_key = collection + ":" + record_id
            cached = self.record_cache.get(cache_key)
            if cached is not None:
                return Record.from_dict(cached)
            raw = self._data.get(collection, {}).get(record_id)
            if raw:
                self.record_cache.set(cache_key, raw)
                return Record.from_dict(raw)
            return None

    def get_many(self, collection: str,
                 ids: List[str]) -> List[Record]:
        output = []
        with self._lock:
            coll = self._data.get(collection, {})
            for rid in ids:
                raw = coll.get(rid)
                if raw:
                    output.append(Record.from_dict(raw))
        return output

    def update(self, collection: str, record_id: str,
               data: Dict) -> Optional[Record]:
        with self._lock:
            record = self._raw_update(
                collection, record_id, data
            )
            if record and not self._batch_mode:
                self._flush_one(collection)
            return record

    def _raw_update(self, collection: str, record_id: str,
                    data: Dict) -> Optional[Record]:
        raw = self._data.get(collection, {}).get(record_id)
        if not raw:
            return None
        record = Record.from_dict(raw)
        self.indexes.unindex_record(
            collection, record_id, record.data
        )
        self.indexes.unindex_record_sorted(
            collection, record_id, record.data
        )
        record.data.update(data)
        record.updated_at = time.time()
        record.version += 1
        if not self._batch_mode and not self._is_large:
            self.timetravel.record_version(
                collection, record_id, record.data,
                version=record.version, deleted=False,
            )
        new_raw = record.to_dict()
        self._data[collection][record_id] = new_raw
        self.storage.append_wal(
            collection, WAL.OP_UPDATE, record_id, new_raw
        )
        self._stats["wal_appends"] += 1
        self.indexes.index_record(
            collection, record_id, record.data
        )
        self.indexes.index_record_sorted(
            collection, record_id, record.data
        )
        self._stats["writes"] += 1
        self.record_cache.invalidate(
            collection + ":" + record_id
        )
        self.query_cache.invalidate_collection(collection)
        self.events.emit("record.updated", {
            "collection": collection,
            "id": record_id,
            "data": record.data,
        })
        if getattr(self, "cdc_stream", None):
            self.cdc_stream.emit(
                "update", collection, record_id,
                data=record.data,
            )
        return record

    def delete(self, collection: str, record_id: str) -> bool:
        with self._lock:
            success = self._raw_delete(collection, record_id)
            if success and not self._batch_mode:
                self._flush_one(collection)
            return success

    def _raw_delete(self, collection: str,
                    record_id: str) -> bool:
        coll = self._data.get(collection, {})
        if record_id not in coll:
            return False
        raw = coll[record_id]
        self.indexes.unindex_record(
            collection, record_id, raw.get("data", {})
        )
        self.indexes.unindex_record_sorted(
            collection, record_id, raw.get("data", {})
        )
        current_version = raw.get("version", 1) + 1
        self.timetravel.record_version(
            collection, record_id, {},
            version=current_version, deleted=True,
        )
        del coll[record_id]
        self.storage.append_wal(
            collection, WAL.OP_DELETE, record_id, None
        )
        self._stats["wal_appends"] += 1
        self._stats["deletes"] += 1
        self.record_cache.invalidate(
            collection + ":" + record_id
        )
        self.query_cache.invalidate_collection(collection)
        self.events.emit("record.deleted", {
            "collection": collection,
            "id": record_id,
        })
        if getattr(self, "cdc_stream", None):
            self.cdc_stream.emit(
                "delete", collection, record_id,
            )
        return True

    def delete_many(self, collection: str,
                    ids: List[str]) -> int:
        count = 0
        with self._lock:
            for rid in ids:
                if self._raw_delete(collection, rid):
                    count += 1
            if count:
                self._flush_one(collection)
        return count

    def update_many(self, collection: str,
                    filter_fn: Callable,
                    data: Dict) -> int:
        count = 0
        with self._lock:
            for rid, raw in list(
                self._data.get(collection, {}).items()
            ):
                if filter_fn(raw.get("data", {})):
                    if self._raw_update(collection, rid, data):
                        count += 1
            if count:
                self._flush_one(collection)
        return count

    # --------------------------------------------------------
    # Query
    # --------------------------------------------------------

    def query(self, collection: str) -> Query:
        with self._lock:
            self._stats["queries"] += 1
            records = list(
                self._data.get(collection, {}).values()
            )
        return Query(records)

    def find_by_index(self, collection: str, field: str,
                      value: Any) -> List[Record]:
        ids = self.indexes.search(collection, field, value)
        return self.get_many(collection, ids)

    def find_by_index_dicts(self, collection: str, field: str,
                            value: Any) -> List[Dict]:
        """Fast lookup - return raw dicts, no Record wrapper."""
        ids = self.indexes.search(collection, field, value)
        coll = self._data.get(collection, {})
        return [coll[i] for i in ids if i in coll]

    def find_prefix(self, collection: str, field: str,
                    prefix: str) -> List[Record]:
        ids = self.indexes.search_prefix(
            collection, field, prefix
        )
        return self.get_many(collection, ids)

    # --------------------------------------------------------
    # Full-Text Search
    # --------------------------------------------------------

    def text_search(self, collection: str, keyword: str,
                    limit: int = 50) -> List[Record]:
        kw = str(keyword).lower()
        output = []
        with self._lock:
            for raw in self._data.get(collection, {}).values():
                text = json.dumps(
                    raw.get("data", {}), default=str
                ).lower()
                if kw in text:
                    output.append(Record.from_dict(raw))
                    if len(output) >= limit:
                        break
        return output

    # --------------------------------------------------------
    # Transactions
    # --------------------------------------------------------

    def transaction(self) -> Transaction:
        self._stats["transactions"] += 1
        return Transaction(self).begin()

    def _snapshot(self) -> Dict:
        with self._lock:
            return json.loads(
                json.dumps(self._data, default=str)
            )

    def _restore_snapshot(self, snapshot: Dict):
        with self._lock:
            self._data = snapshot

    # --------------------------------------------------------
    # Vector Search
    # --------------------------------------------------------

    def vector_search(self, collection: str,
                      query_vector: List[float],
                      top_k: int = 5,
                      field: str = "_vector") -> List[Dict]:
        if not isinstance(query_vector, list) or not query_vector:
            return []
        scored = []
        with self._lock:
            for raw in self._data.get(collection, {}).values():
                vec = raw.get("data", {}).get(field)
                if not isinstance(vec, list):
                    continue
                if len(vec) != len(query_vector):
                    continue
                score = self._cosine(query_vector, vec)
                scored.append((score, raw))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {"score": round(s, 6), **r}
            for s, r in scored[:top_k]
        ]

    @staticmethod
    def _cosine(a: List[float], b: List[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(y * y for y in b) ** 0.5
        return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0

    # --------------------------------------------------------
    # Aggregation
    # --------------------------------------------------------

    def aggregate(self, collection: str, field: str,
                  op: str = "sum") -> Any:
        values = []
        with self._lock:
            for raw in self._data.get(collection, {}).values():
                v = raw.get("data", {}).get(field)
                if isinstance(v, (int, float))                         and not isinstance(v, bool):
                    values.append(v)
        if not values:
            return 0 if op != "avg" else None
        op = op.lower()
        if op == "sum":
            return sum(values)
        if op == "avg":
            return sum(values) / len(values)
        if op == "min":
            return min(values)
        if op == "max":
            return max(values)
        if op == "count":
            return len(values)
        return None

    def group_by(self, collection: str, field: str,
                 aggregate_field: str = None,
                 aggregate_op: str = "count") -> Dict:
        groups: Dict[Any, List[Dict]] = {}
        with self._lock:
            for raw in self._data.get(collection, {}).values():
                data = raw.get("data", {})
                key = data.get(field, "__none__")
                if isinstance(key, (list, dict)):
                    key = str(key)
                groups.setdefault(key, []).append(data)

        result = {}
        for k, items in groups.items():
            if aggregate_field and aggregate_op != "count":
                values = [
                    i.get(aggregate_field) for i in items
                    if isinstance(i.get(aggregate_field),
                                  (int, float))
                    and not isinstance(
                        i.get(aggregate_field), bool
                    )
                ]
                if not values:
                    result[k] = 0
                elif aggregate_op == "sum":
                    result[k] = sum(values)
                elif aggregate_op == "avg":
                    result[k] = sum(values) / len(values)
                elif aggregate_op == "min":
                    result[k] = min(values)
                elif aggregate_op == "max":
                    result[k] = max(values)
                else:
                    result[k] = len(values)
            else:
                result[k] = len(items)
        return result

    def distinct(self, collection: str, field: str) -> List[Any]:
        seen = set()
        output = []
        with self._lock:
            for raw in self._data.get(collection, {}).values():
                v = raw.get("data", {}).get(field)
                if isinstance(v, (list, dict)):
                    v = str(v)
                if v not in seen:
                    seen.add(v)
                    output.append(v)
        return output

    # --------------------------------------------------------
    # Statistics
    # --------------------------------------------------------

    def stats(self) -> Dict:
        with self._lock:
            wal_total = sum(
                self.storage.wal_size(c)
                for c in self._data.keys()
            )
            snapshot_total = sum(
                self.storage.snapshot_size(c)
                for c in self._data.keys()
            )
            return {
                **self._stats,
                "collections": len(self._data),
                "total_records": sum(
                    len(c) for c in self._data.values()
                ),
                "uptime_sec": round(
                    time.time() - self._started, 2
                ),
                "data_dir": self.config.DATA_DIR,
                "wal_bytes": wal_total,
                "snapshot_bytes": snapshot_total,
                "storage_format": "binary+wal",
                "record_cache": self.record_cache.stats(),
                "timetravel": self.timetravel.stats(),
                "query_cache": self.query_cache.stats(),
            }

    def health(self) -> Dict:
        ok = True
        try:
            self.storage.list_collections()
        except Exception:
            ok = False
        return {
            "status": "ok" if ok else "degraded",
            "uptime_sec": round(
                time.time() - self._started, 2
            ),
            "storage": "binary+wal",
        }

    def checkpoint(self):
        """Force snapshot and reset WAL."""
        with self._lock:
            self._flush_all()

    def close(self):
        with self._lock:
            self._flush_all()
            self.storage.close_all()
            try:
                self.locks.release_all()
            except Exception:
                pass

    def begin_batch(self):
        """Enable batch mode + turbo mode."""
        self._batch_mode = True
        self._turbo_mode = True  # <-- BARU
        try:
            self.storage.set_sync_mode(False)
        except Exception:
            pass

    def end_batch(self):
        """Disable turbo + batch, then rebuild indexes + flush."""
        self._turbo_mode = False
        self._batch_mode = False

        # Rebuild indexes setelah turbo insert
        for coll_name in list(self._data.keys()):
            try:
                self.indexes.rebuild(
                    coll_name,
                    self._data.get(coll_name, {})
                )
            except Exception:
                pass

        try:
            self.storage.flush_all_wal()
            self.storage.set_sync_mode(True)
        except Exception:
            pass
        self._flush_all()

    def _ensure(self, name: str):
        if name not in self._data:
            self._data[name] = {}
