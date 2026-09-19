"""
RayzorgenDB Sharding

Split data across multiple shards by hash.
Each shard is a separate database.

Usage:
    sharded = ShardedDB(["./shard0", "./shard1", "./shard2"])
    users = sharded.collection("users")
    users.insert({"nama": "Budi", "user_id": "u1"})
    # Automatically routed ke shard based on user_id
"""

import hashlib
import os
import threading
from typing import Any, Dict, List, Optional


class ShardRouter:
    """Hash-based shard routing."""

    def __init__(self, n_shards: int,
                 shard_key: str = None):
        self.n_shards = n_shards
        self.shard_key = shard_key

    def route(self, key: Any) -> int:
        """Return shard index for key."""
        h = hashlib.md5(str(key).encode()).digest()
        return int.from_bytes(h[:4], "big") % self.n_shards

    def route_record(self, data: Dict) -> int:
        """Route based on record data."""
        if self.shard_key and self.shard_key in data:
            return self.route(data[self.shard_key])
        # Fallback: hash of full data
        return self.route(str(sorted(data.items())))


class ShardedCollection:
    """Collection yang di-shard across multiple databases."""

    def __init__(self, sharded_db, name: str):
        self.sharded = sharded_db
        self.name = name
        self.router = sharded_db.router

    def insert(self, data: Dict):
        shard_id = self.router.route_record(data)
        db = self.sharded.shards[shard_id]
        return db.collection(self.name).insert(data)

    def insert_many(self, items: List[Dict]):
        result = []
        for d in items:
            result.append(self.insert(d))
        return result

    def get(self, record_id: str, shard_key: str = None):
        """Get record. Requires shard_key atau cari di semua."""
        if shard_key is not None:
            shard_id = self.router.route(shard_key)
            return self.sharded.shards[shard_id].collection(
                self.name
            ).get(record_id)
        # Search all shards
        for db in self.sharded.shards:
            rec = db.collection(self.name).get(record_id)
            if rec:
                return rec
        return None

    def all(self) -> List:
        result = []
        for db in self.sharded.shards:
            result.extend(db.collection(self.name).all())
        return result

    def count(self) -> int:
        total = 0
        for db in self.sharded.shards:
            total += db.collection(self.name).count()
        return total

    def query(self):
        """Query across all shards."""
        return ShardedQuery(self)

    def delete(self, record_id: str) -> bool:
        for db in self.sharded.shards:
            coll = db.collection(self.name)
            if coll.exists(record_id):
                return coll.delete(record_id)
        return False

    def update(self, record_id: str, data: Dict):
        for db in self.sharded.shards:
            coll = db.collection(self.name)
            if coll.exists(record_id):
                return coll.update(record_id, data)
        return None


class ShardedQuery:
    """Query across shards."""

    def __init__(self, sharded_collection):
        self.sharded = sharded_collection
        self._wheres = []
        self._limit = None
        self._order = None
        self._desc = False

    def where(self, field, op, value):
        self._wheres.append((field, op, value))
        return self

    def limit(self, n):
        self._limit = n
        return self

    def order_by(self, field, desc=False):
        self._order = field
        self._desc = desc
        return self

    def all(self):
        result = []
        for db in self.sharded.sharded.shards:
            coll = db.collection(self.sharded.name)
            q = coll.query()
            for f, op, v in self._wheres:
                q = q.where(f, op, v)
            # q.all() returns list of dicts
            for r in q.all():
                if hasattr(r, "to_dict"):
                    result.append(r.to_dict())
                else:
                    result.append(r)

        if self._order:
            result.sort(
                key=lambda r: r["data"].get(self._order) or "",
                reverse=self._desc,
            )
        if self._limit:
            result = result[:self._limit]
        return result

    def count(self):
        return len(self.all())

    def first(self):
        r = self.all()
        return r[0] if r else None


class ShardedDB:
    """
    Sharded database across multiple shards.

    Usage:
        db = ShardedDB(["./s0", "./s1", "./s2"],
                       shard_key="user_id")
        users = db.collection("users")
        users.insert({"user_id": "u123", "nama": "Budi"})
    """

    def __init__(self, data_dirs: List[str],
                 shard_key: str = None,
                 config=None):
        from rayzorgendb import RayzorgenDB, Config

        self.data_dirs = data_dirs
        self.n_shards = len(data_dirs)
        self.shard_key = shard_key
        self.router = ShardRouter(self.n_shards, shard_key)

        self.shards = []
        for d in data_dirs:
            if config is None:
                cfg = Config(DATA_DIR=d)
            else:
                cfg = config.clone()
                cfg.DATA_DIR = d
            self.shards.append(RayzorgenDB(cfg))

        self._lock = threading.RLock()
        self._collections = {}

    def collection(self, name: str) -> ShardedCollection:
        if name not in self._collections:
            self._collections[name] = ShardedCollection(
                self, name
            )
        return self._collections[name]

    def stats(self) -> Dict:
        shards_info = []
        total_records = 0
        for i, db in enumerate(self.shards):
            s = db.stats()
            shards_info.append({
                "shard_id": i,
                "dir": self.data_dirs[i],
                "records": s["total_records"],
            })
            total_records += s["total_records"]
        return {
            "n_shards": self.n_shards,
            "shard_key": self.shard_key,
            "total_records": total_records,
            "shards": shards_info,
        }

    def rebalance(self):
        """Rebalance: redistribute records based on shard_key."""
        # Sederhana: baca semua, hapus, tulis ulang
        from collections import defaultdict
        buckets = defaultdict(list)
        for db in self.shards:
            for coll_name in db.collections():
                for rec in db.collection(coll_name).all():
                    buckets[coll_name].append(rec.data)

        # Hapus semua
        for db in self.shards:
            for coll_name in db.collections():
                db.drop_collection(coll_name)

        # Tulis ulang
        total = 0
        for coll_name, items in buckets.items():
            for data in items:
                shard_id = self.router.route_record(data)
                self.shards[shard_id].collection(
                    coll_name
                ).insert(data)
                total += 1

        return {"rebalanced": total}

    def close(self):
        for db in self.shards:
            try:
                db.close()
            except Exception:
                pass


__all__ = ["ShardedDB", "ShardedCollection", "ShardRouter"]
