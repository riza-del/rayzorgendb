"""
RayzorgenDB Async API

Async wrapper for Telegram bots, FastAPI, and other async apps.

Usage:
    from rayzorgendb.async_api import AsyncDB

    db = AsyncDB()
    users = db.collection("users")
    await users.insert({"nama": "Budi"})
    results = await users.query().where("umur", "gt", 20).all()
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from rayzorgendb import RayzorgenDB, Config


_executor = ThreadPoolExecutor(max_workers=4)


async def _run(fn, *args, **kwargs):
    """Run sync function in thread pool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _executor, lambda: fn(*args, **kwargs)
    )


class AsyncQuery:
    """Async version of query."""

    def __init__(self, query):
        self._query = query

    async def all(self):
        return await _run(self._query.all)

    async def first(self):
        return await _run(self._query.first)

    async def count(self):
        return await _run(self._query.count)

    def where(self, field, op, value):
        self._query = self._query.where(field, op, value)
        return self

    def order_by(self, field, desc=False):
        self._query = self._query.order_by(field, desc=desc)
        return self

    def limit(self, n):
        self._query = self._query.limit(n)
        return self

    def skip(self, n):
        self._query = self._query.skip(n)
        return self


class AsyncCollection:
    """Async version of Collection."""

    def __init__(self, collection):
        self._coll = collection

    async def insert(self, data):
        return await _run(self._coll.insert, data)

    async def insert_many(self, items):
        return await _run(self._coll.insert_many, items)

    async def get(self, record_id):
        return await _run(self._coll.get, record_id)

    async def all(self):
        return await _run(self._coll.all)

    async def update(self, record_id, data):
        return await _run(self._coll.update, record_id, data)

    async def delete(self, record_id):
        return await _run(self._coll.delete, record_id)

    async def count(self):
        return await _run(self._coll.count)

    async def search(self, keyword, limit=50):
        return await _run(self._coll.search, keyword, limit)

    async def find(self, **equals):
        return await _run(self._coll.find, **equals)

    async def history(self, record_id):
        return await _run(self._coll.history, record_id)

    async def aggregate(self, field, op="sum"):
        return await _run(self._coll.aggregate, field, op)

    async def group_by(self, field, agg_field=None, agg_op="count"):
        return await _run(
            self._coll.group_by, field, agg_field, agg_op
        )

    def query(self):
        return AsyncQuery(self._coll.query())

    def join(self, other, on, join_type="left", as_=None):
        return self._coll.join(other, on, join_type, as_)


class AsyncDB:
    """Async wrapper for RayzorgenDB."""

    def __init__(self, config: Config = None):
        self._db = RayzorgenDB(config)
        self._collections = {}

    def collection(self, name: str) -> AsyncCollection:
        if name not in self._collections:
            coll = self._db.collection(name)
            self._collections[name] = AsyncCollection(coll)
        return self._collections[name]

    async def begin_batch(self):
        self._db.begin_batch()

    async def end_batch(self):
        self._db.end_batch()

    async def stats(self):
        return await _run(self._db.stats)

    async def close(self):
        await _run(self._db.close)

    @property
    def core(self):
        return self._db.core


__all__ = ["AsyncDB", "AsyncCollection", "AsyncQuery"]
