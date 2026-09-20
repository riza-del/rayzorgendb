import os
"""
RayzorgenDB Public API
Clean facade for the database.
"""

from typing import Any, Dict, List, Optional

from rayzorgendb.core.engine import (
    RayzorgenCore, Record, Transaction,
)
from rayzorgendb.query.builder import Query
from rayzorgendb.config import DEFAULT_CONFIG


class Collection:
    """Handle for a single collection."""

    def __init__(self, core: RayzorgenCore, name: str):
        self.core = core
        self.name = name

    # --------------------------------------------------------
    # Basic CRUD
    # --------------------------------------------------------

    def insert(self, data: Dict) -> Record:
        return self.core.insert(self.name, data)

    def insert_many_chunked(self, items: List[Dict],
                             chunk_size: int = 10000,
                             on_progress=None):
        """
        Insert many records safely with RAM monitoring.
        Auto-checkpoints between chunks. Stops gracefully if RAM low.

        Usage:
            users.insert_many_chunked(
                [{...} for i in range(1000000)],
                chunk_size=10000,
                on_progress=lambda d, t: print(f"{d}/{t}"),
            )
        """
        from rayzorgendb.stability import insert_chunked
        ids = insert_chunked(
            self, items,
            chunk_size=chunk_size,
            on_progress=on_progress,
        )
        return self.core.get_many(self.name, ids)

    def insert_many(self, items: List[Dict]) -> List[Record]:
        return [
            self.core.insert(self.name, d) for d in items
        ]

    def get(self, record_id: str) -> Optional[Record]:
        return self.core.get(self.name, record_id)

    def get_many(self, ids: List[str]) -> List[Record]:
        return self.core.get_many(self.name, ids)

    def all(self, limit: int = None,
            offset: int = 0) -> List[Record]:
        """Return all records, optional limit and offset."""
        data = self.core._data.get(self.name, {})
        if limit is None and offset == 0:
            return [Record.from_dict(r) for r in data.values()]
        items = list(data.values())
        if offset:
            items = items[offset:]
        if limit:
            items = items[:limit]
        return [Record.from_dict(r) for r in items]

    def update(self, record_id: str,
               data: Dict) -> Optional[Record]:
        return self.core.update(self.name, record_id, data)

    def update_many(self, filter_fn, data: Dict) -> int:
        return self.core.update_many(
            self.name, filter_fn, data
        )

    def delete(self, record_id: str) -> bool:
        return self.core.delete(self.name, record_id)

    def delete_many(self, ids: List[str]) -> int:
        return self.core.delete_many(self.name, ids)

    def count(self) -> int:
        return len(self.core._data.get(self.name, {}))

    def exists(self, record_id: str) -> bool:
        return record_id in self.core._data.get(self.name, {})

    # --------------------------------------------------------
    # Query
    # --------------------------------------------------------

    def query(self) -> Query:
        return self.core.query(self.name)

    def find(self, **equals) -> List[Record]:
        q = self.query()
        for k, v in equals.items():
            q = q.where(k, "eq", v)
        return [Record.from_dict(r) for r in q.all()]

    def search(self, keyword: str,
               limit: int = 50) -> List[Record]:
        return self.core.text_search(
            self.name, keyword, limit
        )

    # --------------------------------------------------------
    # Index
    # --------------------------------------------------------

    def create_index(self, field: str) -> bool:
        self.core.indexes.create(self.name, field)
        for rid, raw in self.core._data.get(
                self.name, {}).items():
            self.core.indexes.index_record(
                self.name, rid, raw.get("data", {})
            )
        return True

    def drop_index(self, field: str) -> bool:
        return self.core.indexes.drop(self.name, field)

    def rebuild_indexes(self):
        self.core.indexes.rebuild(
            self.name, self.core._data.get(self.name, {})
        )

    def indexes(self) -> List[str]:
        return self.core.indexes.list_indexes(self.name)

    def create_sorted_index(self, field: str) -> bool:
        """Create B+ Tree index for range queries."""
        self.core.indexes.create_sorted(self.name, field)
        for rid, raw in self.core._data.get(
                self.name, {}).items():
            self.core.indexes.index_record_sorted(
                self.name, rid, raw.get("data", {})
            )
        return True

    def drop_sorted_index(self, field: str) -> bool:
        return self.core.indexes.drop_sorted(self.name, field)

    def sorted_indexes(self) -> List[str]:
        return self.core.indexes.list_sorted_indexes(self.name)

    def range(self, field: str, start=None,
              end=None) -> List[Record]:
        """Range query using B+ Tree index."""
        raws = self.core.range_raw(
            self.name, field, start, end
        )
        return [Record.from_dict(r) for r in raws]

    def range_raw(self, field: str, start=None,
                  end=None) -> List[Dict]:
        """Fast range query - return raw dicts."""
        return self.core.range_raw(
            self.name, field, start, end
        )

    def find_by(self, field: str, value: Any) -> List[Record]:
        raws = self.core.find_by_index_raw(
            self.name, field, value
        )
        return [Record.from_dict(r) for r in raws]

    def find_by_raw(self, field: str, value: Any) -> List[Dict]:
        """Fast lookup - return raw dicts, no wrapper."""
        return self.core.find_by_index_raw(
            self.name, field, value
        )

    def find_prefix(self, field: str,
                    prefix: str) -> List[Record]:
        return self.core.find_prefix(
            self.name, field, prefix
        )

    # --------------------------------------------------------
    # Aggregation
    # --------------------------------------------------------

    def aggregate(self, field: str, op: str = "sum") -> Any:
        return self.core.aggregate(self.name, field, op)

    def group_by(self, field: str, agg_field: str = None,
                 agg_op: str = "count") -> Dict:
        return self.core.group_by(
            self.name, field, agg_field, agg_op
        )

    def distinct(self, field: str) -> List[Any]:
        return self.core.distinct(self.name, field)

    # --------------------------------------------------------
    # Vector
    # --------------------------------------------------------

    def vector_search(self, query_vector: List[float],
                      top_k: int = 5,
                      field: str = "_vector") -> List[Dict]:
        return self.core.vector_search(
            self.name, query_vector, top_k, field
        )

    # --------------------------------------------------------
    # JOIN
    # --------------------------------------------------------

    def join(self, other_collection: str,
             on: tuple,
             join_type: str = "left",
             as_: str = None):
        left_key, right_key = on
        return self.core.join_engine.join(
            self.name, other_collection,
            left_key, right_key,
            join_type, as_,
        )

    def join_many(self, joins: list):
        return self.core.join_engine.join_many(
            self.name, joins
        )

    # --------------------------------------------------------
    # Backup
    # --------------------------------------------------------

    def backup(self, path: str) -> bool:
        return self.core.storage.backup(self.name, path)

    def restore(self, path: str) -> bool:
        success = self.core.storage.restore(self.name, path)
        if success:
            self.core._data[self.name] =                 self.core.storage.load(self.name)
            self.rebuild_indexes()
        return success

    # --------------------------------------------------------
    # Time Travel
    # --------------------------------------------------------

    def history(self, record_id: str) -> List[Dict]:
        """
        Return all versions of a record.
        Each entry: {"version": ..., "at": ..., "data": ...}
        """
        return self.core.timetravel.history(
            self.name, record_id
        )

    def at(self, timestamp) -> "TimeSnapshot":
        """
        Return a snapshot of the collection at a given time.
        Accepts either a Unix timestamp (float) or ISO string.

        Usage:
            snap = users.at("2026-09-10").all()
            snap = users.at(1699999999.0).all()
        """
        ts = _parse_timestamp(timestamp)
        return TimeSnapshot(self.core, self.name, ts)

    def diff(self, record_id: str,
             version_a: int,
             version_b: int) -> Dict:
        """Compare two versions of a record."""
        return self.core.timetravel.diff(
            self.name, record_id, version_a, version_b
        )

    def changes_between(self, start, end) -> List[Dict]:
        """Return all changes between two timestamps."""
        ts_start = _parse_timestamp(start)
        ts_end = _parse_timestamp(end)
        return self.core.timetravel.changes_between(
            self.name, ts_start, ts_end
        )

    def restore_version(self, record_id: str,
                        version: int) -> Optional[Record]:
        """
        Restore a record to an old version.
        Creates a new version with the old data.
        """
        versions = self.core.timetravel.history(
            self.name, record_id
        )
        for v in versions:
            if v["version"] == version and not v["deleted"]:
                return self.update(record_id, v["data"])
        return None

    # --------------------------------------------------------
    # HNSW Vector Search
    # --------------------------------------------------------

    def build_hnsw_index(self, dim: int,
                          vector_field: str = "_vector",
                          m: int = 16):
        """Build HNSW index from collection."""
        from rayzorgendb.hnsw.index import HNSWIndex
        if not hasattr(self, "_hnsw_indexes"):
            self._hnsw_indexes = {}
        idx = HNSWIndex(dim=dim, m=m)
        for rid, raw in self.core._data.get(
                self.name, {}).items():
            vec = raw.get("data", {}).get(vector_field)
            if isinstance(vec, list) and len(vec) == dim:
                idx.insert(rid, vec)
        self._hnsw_indexes[dim] = idx
        return idx

    def vector_search_hnsw(self, query_vec: list,
                            top_k: int = 5) -> list:
        """Fast HNSW vector search."""
        if not hasattr(self, "_hnsw_indexes"):
            return []
        dim = len(query_vec)
        idx = self._hnsw_indexes.get(dim)
        if idx is None:
            return []
        results = idx.search(query_vec, k=top_k)
        out = []
        for rid, score in results:
            raw = self.core._data.get(self.name, {}).get(rid)
            if raw:
                out.append({
                    "id": rid,
                    "score": round(score, 4),
                    **raw,
                })
        return out

    # --------------------------------------------------------
    # Columnar Analytics
    # --------------------------------------------------------

    def columnar(self):
        """Get columnar view of this collection."""
        from rayzorgendb.columnar.store import ColumnarStore
        cs = ColumnarStore()
        rows = list(self.core._data.get(
            self.name, {}
        ).values())
        cs.load_from_rows(rows)
        return cs

    def columnar_aggregate(self, field: str,
                            op: str = "sum"):
        return self.columnar().aggregate(field, op)

    def columnar_group_by(self, field: str,
                           agg_field: str = None,
                           agg_op: str = "count"):
        return self.columnar().group_by(
            field, agg_field, agg_op
        )

    # --------------------------------------------------------
    # Hybrid Search
    # --------------------------------------------------------

    def build_hybrid_index(self, text_field: str,
                            vector_field: str = "_vector"):
        """Build hybrid search index (BM25 + vector)."""
        from rayzorgendb.hybrid.search import HybridSearch
        hs = HybridSearch()
        for rid, raw in self.core._data.get(
                self.name, {}).items():
            data = raw.get("data", {})
            text = str(data.get(text_field, ""))
            vec = data.get(vector_field)
            hs.add_document(
                rid, text,
                vec if isinstance(vec, list) else None,
            )
        self._hybrid = hs
        return hs

    def hybrid_search(self, query: str = "",
                       query_vector: list = None,
                       top_k: int = 5,
                       method: str = "hybrid"):
        """Search using hybrid (BM25 + vector)."""
        if not hasattr(self, "_hybrid"):
            return []
        return self._hybrid.search(
            query, query_vector, top_k, method
        )

    def drop(self) -> bool:
        return self.core.drop_collection(self.name)

    def analyze(self):
        """Analyze collection for query optimizer."""
        from rayzorgendb.optimizer.engine import QueryOptimizer
        if not hasattr(self.core, "_optimizer"):
            self.core._optimizer = QueryOptimizer(self.core)
        self.core._optimizer.analyze(self.name)
        return self.core._optimizer.stats.all(self.name)

    def explain_plan(self, sql: str) -> str:
        """Show execution plan for SQL query."""
        from rayzorgendb.sql.parser import parse, Select
        from rayzorgendb.optimizer.engine import QueryOptimizer
        if not hasattr(self.core, "_optimizer"):
            self.core._optimizer = QueryOptimizer(self.core)
        ast = parse(sql)
        if not isinstance(ast, Select):
            return "Only SELECT supported"
        self.core._optimizer.analyze(ast.table)

        # Extract filters dari WHERE
        filters = []
        self._extract_filters_v2(ast.where, filters)

        plan = self.core._optimizer.optimize_select(
            ast.table, filters, order_by=None,
            limit=ast.limit,
            index_manager=self.core.indexes,
        )
        return plan.explain()

    def _extract_filters_v2(self, node, out):
        """Extract simple filters dari AST."""
        from rayzorgendb.sql.parser import (
            BinOp, Column, Literal, Between, InList, Like,
        )
        if node is None:
            return
        if isinstance(node, BinOp) and node.op in ("AND", "OR"):
            self._extract_filters_v2(node.left, out)
            self._extract_filters_v2(node.right, out)
            return
        if isinstance(node, BinOp) and isinstance(node.left, Column):
            value = (
                node.right.value
                if isinstance(node.right, Literal) else None
            )
            op_map = {
                "=": "eq", "!=": "ne", "<>": "ne",
                "<": "lt", ">": "gt",
                "<=": "lte", ">=": "gte",
            }
            out.append({
                "field": node.left.name,
                "op": op_map.get(node.op, "eq"),
                "value": value,
            })
        elif isinstance(node, Between) and isinstance(
                node.expr, Column):
            out.append({
                "field": node.expr.name,
                "op": "between",
                "value": None,
            })
        elif isinstance(node, InList) and isinstance(
                node.expr, Column):
            out.append({
                "field": node.expr.name,
                "op": "in",
                "value": None,
            })
        elif isinstance(node, Like) and isinstance(
                node.expr, Column):
            out.append({
                "field": node.expr.name,
                "op": "contains",
                "value": None,
            })

    def export_json(self, path: str = None) -> str:
        """Export collection ke JSON."""
        from rayzorgendb.export_import import Exporter
        return Exporter(self).to_json(path)

    def export_csv(self, path: str = None) -> str:
        """Export collection ke CSV."""
        from rayzorgendb.export_import import Exporter
        return Exporter(self).to_csv(path)

    def import_json(self, source: str) -> int:
        """Import dari JSON file atau string."""
        from rayzorgendb.export_import import Importer
        return Importer(self).from_json(source)

    def import_csv(self, source: str) -> int:
        """Import dari CSV file atau string."""
        from rayzorgendb.export_import import Importer
        return Importer(self).from_csv(source)

    def analyze(self):
        """Analyze collection untuk query optimizer."""
        from rayzorgendb.optimizer.engine import QueryOptimizer
        if not hasattr(self.core, "_optimizer"):
            self.core._optimizer = QueryOptimizer(self.core)
        self.core._optimizer.analyze(self.name)
        return self.core._optimizer.stats.all(self.name)

    def explain_plan(self, sql: str) -> str:
        """Show execution plan for SQL query."""
        from rayzorgendb.sql.parser import parse, Select
        from rayzorgendb.optimizer.engine import QueryOptimizer
        if not hasattr(self.core, "_optimizer"):
            self.core._optimizer = QueryOptimizer(self.core)
        ast = parse(sql)
        if not isinstance(ast, Select):
            return "Only SELECT supported"
        self.core._optimizer.analyze(ast.table)

        # Extract filters dari WHERE
        filters = []
        self._extract_filters_v2(ast.where, filters)

        plan = self.core._optimizer.optimize_select(
            ast.table, filters, order_by=None,
            limit=ast.limit,
            index_manager=self.core.indexes,
        )
        return plan.explain()

    def _extract_filters_v2(self, node, out):
        """Extract simple filters dari AST."""
        from rayzorgendb.sql.parser import (
            BinOp, Column, Literal, Between, InList, Like,
        )
        if node is None:
            return
        if isinstance(node, BinOp) and node.op in ("AND", "OR"):
            self._extract_filters_v2(node.left, out)
            self._extract_filters_v2(node.right, out)
            return
        if isinstance(node, BinOp) and isinstance(node.left, Column):
            value = (
                node.right.value
                if isinstance(node.right, Literal) else None
            )
            op_map = {
                "=": "eq", "!=": "ne", "<>": "ne",
                "<": "lt", ">": "gt",
                "<=": "lte", ">=": "gte",
            }
            out.append({
                "field": node.left.name,
                "op": op_map.get(node.op, "eq"),
                "value": value,
            })
        elif isinstance(node, Between) and isinstance(
                node.expr, Column):
            out.append({
                "field": node.expr.name,
                "op": "between",
                "value": None,
            })
        elif isinstance(node, InList) and isinstance(
                node.expr, Column):
            out.append({
                "field": node.expr.name,
                "op": "in",
                "value": None,
            })
        elif isinstance(node, Like) and isinstance(
                node.expr, Column):
            out.append({
                "field": node.expr.name,
                "op": "contains",
                "value": None,
            })

    def __repr__(self):
        return "<Collection {} count={}>".format(
            self.name, self.count()
        )


class RayzorgenDB:
    """Main database facade."""

    def __init__(self, config=None):
        self.config = config or DEFAULT_CONFIG
        self.core = RayzorgenCore(self.config)
        self._handles: Dict[str, Collection] = {}
        # Smart layer (unified advanced API)
        try:
            from rayzorgendb.smart import Smart
            self.smart = Smart(self)
        except Exception:
            self.smart = None

    # --------------------------------------------------------
    # Collections
    # --------------------------------------------------------

    def collection(self, name: str) -> Collection:
        if name not in self._handles:
            self.core.create_collection(name)
            self._handles[name] = Collection(
                self.core, name
            )
        return self._handles[name]

    def drop_collection(self, name: str) -> bool:
        self._handles.pop(name, None)
        return self.core.drop_collection(name)

    def collections(self) -> List[str]:
        return self.core.list_collections()

    def has_collection(self, name: str) -> bool:
        return self.core.has_collection(name)

    # --------------------------------------------------------
    # Transactions
    # --------------------------------------------------------

    def transaction(self) -> Transaction:
        return self.core.transaction()

    def savepoint_transaction(self):
        """Start a savepoint-capable transaction."""
        from rayzorgendb.savepoint import SavepointTransaction
        return SavepointTransaction(self.core).begin()

    def query_history(self, n: int = 20) -> List[Dict]:
        """Return recent queries."""
        from rayzorgendb.query_history import recent
        return recent(n)

    def slow_queries(self, n: int = 20) -> List[Dict]:
        """Return slow queries."""
        from rayzorgendb.query_history import slow
        return slow(n)

    def query_stats(self) -> Dict:
        """Return query stats."""
        from rayzorgendb.query_history import stats
        return stats()

    # --------------------------------------------------------
    # CDC
    # --------------------------------------------------------

    def cdc(self):
        """Get CDC stream."""
        from rayzorgendb.cdc import CDCStream
        if not hasattr(self.core, "cdc_stream") or \
           self.core.cdc_stream is None:
            self.core.cdc_stream = CDCStream()
        return self.core.cdc_stream

    def on_change(self, callback, collection: str = None,
                   op: str = None):
        """Register CDC listener."""
        return self.cdc().on_change(callback, collection, op)

    # --------------------------------------------------------
    # Time-Series
    # --------------------------------------------------------

    def timeseries(self):
        """Get time-series engine."""
        from rayzorgendb.timeseries import TimeSeries
        if not hasattr(self.core, "_ts"):
            self.core._ts = TimeSeries()
        return self.core._ts

    # --------------------------------------------------------
    # MVCC Multi-Reader
    # --------------------------------------------------------

    def mvcc(self):
        """Get multi-reader MVCC engine."""
        from rayzorgendb.mvcc_multi import MultiReaderMVCC
        if not hasattr(self.core, "_mvcc_multi"):
            self.core._mvcc_multi = MultiReaderMVCC()
        return self.core._mvcc_multi

    # --------------------------------------------------------
    # Paged Storage
    # --------------------------------------------------------

    def paged(self, path: str = None, cache_pages: int = 256):
        """Open paged storage."""
        from rayzorgendb.paged.storage import PagedStorage
        if not hasattr(self.core, "_paged"):
            p = path or os.path.join(
                self.config.DATA_DIR, "pages.pg"
            )
            self.core._paged = PagedStorage(
                p, cache_pages=cache_pages
            )
        return self.core._paged

    # --------------------------------------------------------
    # Events
    # --------------------------------------------------------

    def on(self, event: str, handler):
        self.core.events.on(event, handler)

    def off(self, event: str, handler=None):
        self.core.events.off(event, handler)

    # --------------------------------------------------------
    # Utilities
    # --------------------------------------------------------

    def begin_batch(self):
        """Enable batch mode for fast bulk inserts."""
        self.core.begin_batch()

    def end_batch(self):
        """Flush all pending writes."""
        self.core.end_batch()

    def wal_only(self, enabled: bool = True):
        """Enable WAL-only mode (fast writes)."""
        self.core.set_wal_only(enabled)

    def snapshot(self):
        """Force snapshot to disk."""
        self.core.force_snapshot()

    def stats(self) -> Dict:
        return self.core.stats()

    def health(self) -> Dict:
        return self.core.health()

    def checkpoint(self):
        self.core.checkpoint()

    def flush(self):
        self.core._flush_all()

    def backup_all(self, directory: str) -> int:
        import os
        os.makedirs(directory, exist_ok=True)
        count = 0
        for name in self.collections():
            path = os.path.join(directory, name + ".rdb")
            if self.core.storage.backup(name, path):
                count += 1
        return count

    # --------------------------------------------------------
    # SQL Support
    # --------------------------------------------------------

    def execute(self, sql: str) -> Dict:
        """
        Execute SQL query.

        Mendukung:
            SELECT, INSERT, UPDATE, DELETE
            CREATE TABLE/INDEX, DROP TABLE/INDEX
            JOIN, GROUP BY, HAVING, DISTINCT
            CASE WHEN, COALESCE, fungsi string
            EXPLAIN SELECT ...

        Usage:
            db.execute("SELECT * FROM users WHERE umur > 25")
            db.execute("EXPLAIN SELECT * FROM users WHERE umur > 25")
        """
        sql_stripped = sql.strip()
        # Handle EXPLAIN
        upper = sql_stripped.upper()
        if upper.startswith("EXPLAIN "):
            inner = sql_stripped[8:].strip()
            return self._explain(inner)

        from rayzorgendb.sql.parser import parse
        from rayzorgendb.sql.executor import Executor
        import time as _time
        from rayzorgendb.query_history import record

        t0 = _time.time()
        error = None
        rows = 0
        try:
            ast = parse(sql_stripped)
            executor = Executor(self)
            result = executor.execute(ast)
            rows = len(result.get("rows", []))
            return result
        except Exception as e:
            error = str(e)[:100]
            raise
        finally:
            duration = (_time.time() - t0) * 1000
            try:
                record(
                    sql_stripped, duration,
                    rows=rows, error=error,
                    source="sql",
                )
            except Exception:
                pass

    def _explain(self, sql: str) -> Dict:
        """Generate execution plan for SQL."""
        from rayzorgendb.sql.parser import parse, Select
        from rayzorgendb.optimizer.engine import (
            QueryOptimizer, PlanNode,
        )

        if not hasattr(self.core, "_optimizer"):
            self.core._optimizer = QueryOptimizer(self.core)

        ast = parse(sql)
        if not isinstance(ast, Select):
            return {
                "error": "EXPLAIN only supports SELECT",
                "plan": "",
            }

        # Auto-analyze
        self.core._optimizer.analyze(ast.table)

        # Extract filters
        filters = []
        self._walk_where(ast.where, filters)

        plan = self.core._optimizer.optimize_select(
            ast.table,
            filters,
            order_by=self._extract_order_sql(ast),
            limit=ast.limit,
            index_manager=self.core.indexes,
        )
        return {
            "plan": plan.to_dict(),
            "explain": plan.explain(),
            "cost": round(plan.cost, 2),
            "estimated_rows": plan.rows,
        }

    def _walk_where(self, node, out):
        from rayzorgendb.sql.parser import (
            BinOp, Column, Literal, Between,
            InList, Like,
        )
        if node is None:
            return
        if isinstance(node, BinOp) and node.op in ("AND", "OR"):
            self._walk_where(node.left, out)
            self._walk_where(node.right, out)
            return
        if isinstance(node, BinOp) and isinstance(node.left, Column):
            value = (
                node.right.value
                if isinstance(node.right, Literal) else None
            )
            out.append({
                "field": node.left.name,
                "op": self._op_map(node.op),
                "value": value,
            })
        elif isinstance(node, Between) and isinstance(
                node.expr, Column):
            out.append({
                "field": node.expr.name,
                "op": "between",
                "value": None,
            })
        elif isinstance(node, InList) and isinstance(
                node.expr, Column):
            out.append({
                "field": node.expr.name,
                "op": "in",
                "value": None,
            })
        elif isinstance(node, Like) and isinstance(
                node.expr, Column):
            out.append({
                "field": node.expr.name,
                "op": "contains",
                "value": None,
            })

    @staticmethod
    def _op_map(sql_op):
        return {
            "=": "eq", "!=": "ne", "<>": "ne",
            "<": "lt", ">": "gt",
            "<=": "lte", ">=": "gte",
        }.get(sql_op, "eq")

    @staticmethod
    def _extract_order_sql(ast):
        if ast.order_by:
            first = ast.order_by[0][0]
            from rayzorgendb.sql.parser import Column
            if isinstance(first, Column):
                return first.name
        return None

    def query_sql(self, sql: str) -> List[Dict]:
        """Execute SELECT, return list of rows."""
        result = self.execute(sql)
        return result.get("rows", [])

    # --------------------------------------------------------
    # Query Optimizer
    # --------------------------------------------------------

    def analyze(self):
        """Analyze collection for query optimizer."""
        from rayzorgendb.optimizer.engine import QueryOptimizer
        if not hasattr(self.core, "_optimizer"):
            self.core._optimizer = QueryOptimizer(self.core)
        self.core._optimizer.analyze(self.name)
        return self.core._optimizer.stats.all(self.name)

    def explain_sql(self, sql: str) -> str:
        """
        Show execution plan for SQL query.

        Usage:
            print(db.explain("SELECT * FROM users WHERE umur > 25"))
        """
        from rayzorgendb.sql.parser import (
            parse, Select,
        )
        from rayzorgendb.optimizer.engine import QueryOptimizer

        if not hasattr(self.core, "_optimizer"):
            self.core._optimizer = QueryOptimizer(self.core)

        ast = parse(sql)
        if not isinstance(ast, Select):
            return "EXPLAIN only supports SELECT"

        filters = []
        # Extract simple filters dari WHERE
        self._extract_filters(ast.where, filters)

        plan = self.core._optimizer.optimize_select(
            ast.table,
            filters,
            order_by=self._extract_order(ast),
            limit=ast.limit,
            index_manager=self.core.indexes,
        )
        return plan.explain()

    def _extract_filters(self, node, out):
        """Extract simple filters dari AST WHERE."""
        from rayzorgendb.sql.parser import (
            BinOp, Column, Literal, InList, Between, Like,
        )
        if node is None:
            return
        if isinstance(node, BinOp):
            if node.op in ("AND", "OR"):
                self._extract_filters(node.left, out)
                self._extract_filters(node.right, out)
                return
            # Simple comparison
            if isinstance(node.left, Column):
                field = node.left.name
                value = None
                if isinstance(node.right, Literal):
                    value = node.right.value
                out.append({
                    "field": field,
                    "op": self._sql_op_to_op(node.op),
                    "value": value,
                })
        elif isinstance(node, Between):
            if isinstance(node.expr, Column):
                out.append({
                    "field": node.expr.name,
                    "op": "between",
                    "value": None,
                })
        elif isinstance(node, InList):
            if isinstance(node.expr, Column):
                out.append({
                    "field": node.expr.name,
                    "op": "in",
                    "value": None,
                })
        elif isinstance(node, Like):
            if isinstance(node.expr, Column):
                out.append({
                    "field": node.expr.name,
                    "op": "contains",
                    "value": None,
                })

    @staticmethod
    def _sql_op_to_op(sql_op):
        return {
            "=": "eq",
            "!=": "ne",
            "<>": "ne",
            "<": "lt",
            ">": "gt",
            "<=": "lte",
            ">=": "gte",
        }.get(sql_op, "eq")

    @staticmethod
    def _extract_order(ast):
        if ast.order_by:
            first = ast.order_by[0][0]
            from rayzorgendb.sql.parser import Column
            if isinstance(first, Column):
                return first.name
        return None

    def close(self):
        self.core.close()


# ============================================================
# Time Travel Helpers
# ============================================================

    def metrics(self) -> dict:
        """Return collected metrics."""
        return self.core._metrics.summary()

    def integrity_check(self, collection: str) -> dict:
        """Verify all records checksum."""
        coll = self.collection(collection)
        passed = 0
        failed = 0
        for rec in coll.all():
            expected = self.core._integrity.compute(rec.data)
            if self.core._integrity.verify(rec.data, expected):
                passed += 1
            else:
                failed += 1
        return {
            "collection": collection,
            "passed": passed,
            "failed": failed,
        }


    def set_schema(self, collection: str, schema):
        """Enable schema validation for a collection."""
        from rayzorgendb.schema.validator import Schema
        self.core._schema = schema
        self.core._schema_collection = collection
        return True


    def enable_logging(self, level: str = "INFO",
                       output: str = None):
        """Enable structured logging."""
        from rayzorgendb.logging_config import configure
        self.core._logger = configure(
            level=level, output=output, to_console=False
        )
        return True

    def enable_multi_writer(self):
        """Enable multi-writer optimistic locking."""
        from rayzorgendb.multi_writer import MultiWriter
        self.core._multi_writer = MultiWriter(self.core)
        return True

    def enable_auth(self, users: dict = None):
        """Enable basic authentication."""
        from rayzorgendb.auth import BasicAuth
        self.core._auth = BasicAuth(users or {})
        return True

    def encrypt_at_rest(self, password: str):
        """Enable encryption for data at rest."""
        from rayzorgendb.crypto.cipher import Cipher
        self.core._cipher = Cipher(password)
        return True

    def shard(self, shard_key: str, n_shards: int = 3):
        """Enable sharding across multiple folders."""
        from rayzorgendb.sharding import ShardedDB
        folders = [
            self.config.DATA_DIR + "_shard" + str(i)
            for i in range(n_shards)
        ]
        return ShardedDB(folders, shard_key=shard_key)

    def replicate_to(self, host: str, port: int = 9999):
        """Start as replication primary."""
        from rayzorgendb.replication import ReplicationManager
        mgr = ReplicationManager(self, mode="primary")
        mgr.start_primary(host, port)
        return mgr

    def enable_paged(self, cache_pages: int = 256):
        """Enable paged disk storage."""
        from rayzorgendb.paged.storage import PagedStorage
        import os
        path = os.path.join(
            self.config.DATA_DIR, "pages.pg"
        )
        self.core._paged = PagedStorage(
            path, cache_pages=cache_pages
        )
        return self.core._paged

    def explain_sql(self, sql: str) -> str:
        """Explain execution plan for SQL."""
        from rayzorgendb.sql.parser import parse, Select
        from rayzorgendb.optimizer.engine import QueryOptimizer

        if self.core._optimizer is None:
            self.core._optimizer = QueryOptimizer(self.core)

        ast = parse(sql)
        if not isinstance(ast, Select):
            return "Only SELECT supported"

        self.core._optimizer.analyze(ast.table)
        plan = self.core._optimizer.optimize_select(
            ast.table, [], order_by=None,
            limit=ast.limit,
            index_manager=self.core.indexes,
        )
        return plan.explain()


    def all(self) -> List[Dict]:
        """All records visible at this time."""
        return self.core.timetravel.snapshot_at(
            self.collection, self.timestamp
        )

    def get(self, record_id: str) -> Optional[Dict]:
        """One record visible at this time."""
        return self.core.timetravel.at(
            self.collection, record_id, self.timestamp
        )

    def count(self) -> int:
        return len(self.all())

    def changes_since(self, other_timestamp) -> List[Dict]:
        """Changes between other_timestamp and this timestamp."""
        ts_other = _parse_timestamp(other_timestamp)
        return self.core.timetravel.changes_between(
            self.collection, ts_other, self.timestamp
        )

class TimeSnapshot:
    """Snapshot of a collection at a specific time."""

    def __init__(self, core, collection: str, timestamp: float):
        self.core = core
        self.collection = collection
        self.timestamp = timestamp

    def __repr__(self):
        return "<TimeSnapshot {} at {}>".format(
            self.collection, self.timestamp
        )

    def all(self) -> List[Dict]:
        """All records visible at this time."""
        return self.core.timetravel.snapshot_at(
            self.collection, self.timestamp
        )

    def get(self, record_id: str) -> Optional[Dict]:
        """One record visible at this time."""
        return self.core.timetravel.at(
            self.collection, record_id, self.timestamp
        )

    def count(self) -> int:
        """How many records visible at this time."""
        return len(self.all())

    def changes_since(self, other_timestamp) -> List[Dict]:
        """Changes between other_timestamp and this timestamp."""
        ts_other = _parse_timestamp(other_timestamp)
        return self.core.timetravel.changes_between(
            self.collection, ts_other, self.timestamp
        )

    def predict(self, key: str) -> Dict:
        """Predictive placeholder for time travel."""
        return {
            "at": self.timestamp,
            "predict": key,
            "note": "prediction placeholder",
        }

    def snapshot(self) -> List[Dict]:
        """Alias for all()."""
        return self.all()



def _parse_timestamp(value) -> float:
    """
    Convert various formats to Unix timestamp.
    Accepts: float, int, or ISO string.
    """
    import time as _time
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        # Try ISO format
        s = value.strip()
        for fmt in (
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ):
            try:
                return _time.mktime(
                    _time.strptime(s, fmt)
                )
            except ValueError:
                continue
    raise ValueError(
        "Cannot parse timestamp: " + repr(value)
    )



    # ========================================================
    # INTEGRATED MODULES - enable as needed
    # ========================================================

__all__ = [
    "RayzorgenDB", "Collection", "Transaction", "Record",
    "TimeSnapshot",
]
