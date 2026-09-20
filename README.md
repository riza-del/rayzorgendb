# RayzorgenDB

High-performance embedded database engine built for native execution.

RayzorgenDB delivers a complete storage and query engine within a unified package, combining multiple data models and advanced capabilities into a streamlined, self-contained architecture.

Supported Python versions: 3.8 and newer.

## Overview

Designed for maximum efficiency and portability, RayzorgenDB integrates advanced indexing, custom binary storage, and a robust query layer natively. It eliminates infrastructure overhead, enabling seamless local integration for modern applications.

## Feature Summary

### Storage Engine
- Custom binary format with varint encoding
- Write-Ahead Log with automatic crash recovery
- zlib compression (delivering approximately 82 percent size reduction)
- CRC32 checksum verification
- Paged disk storage supporting datasets exceeding available RAM
- Atomic write operations with configurable fsync policies

### Query Layer
- Native hand-written SQL parser (approximately 1,400 lines)
- Chainable Python query builder interface
- Cost-based query optimizer utilizing statistical analysis
- EXPLAIN and ANALYZE tools for query execution planning
- Full-text search capabilities across all fields
- Advanced aggregations: SUM, AVG, MIN, MAX, and COUNT
- Comprehensive support for GROUP BY, HAVING, and DISTINCT clauses

### Indexing
- Hash indexes optimized for exact equality lookups
- B+ Tree indexes designed for efficient range queries
- Prefix search support
- Dynamic index selection handled by the query optimizer
- Bulk loading mechanisms for rapid index reconstruction

### Relational Operations
- Standard INNER, LEFT, and RIGHT JOIN implementations
- Multi-collection join chaining
- Seamless nested field access
- Advanced filtering applied directly to join results

## Advanced Capabilities

### Multi-Writer DAG Storage

Every write becomes a node in a directed acyclic graph. Multiple writers append to independent branches without lock contention. Branches merge on demand.

    b1 = db.smart.branch("writer_a")
    b2 = db.smart.branch("writer_b")

    db.smart.write_branch(b1, "insert", "users", "u1", {"name": "A"})
    db.smart.write_branch(b2, "insert", "orders", "o1", {"total": 500})

    tips = [db.smart.graph.tip(b1), db.smart.graph.tip(b2)]
    db.smart.merge_branches(tips)

### Scored Queries

Standard queries return binary match results. RayzorgenDB additionally supports weighted scoring, returning ranked results.

    from rayzorgendb.smart import Condition

    conditions = [
        Condition("age", "between", [24, 30], weight=0.5),
        Condition("city", "eq", "Jakarta", weight=0.3),
        Condition("active", "eq", True, weight=0.2),
    ]

    results = db.smart.score("users", conditions).all(limit=10)

### Reactive Fields

Declare a dependency between collections. The target field recalculates on read whenever the source changes.

    db.smart.link(
        source=("orders", "user_id"),
        target=("users", "total_orders"),
        compute=lambda records: len(records),
    )

### Time Travel

Every version of every record is preserved.

    users.history("record-id")
    users.at("2026-01-01").all()
    users.diff("record-id", 1, 3)
    users.restore_version("record-id", 1)

### Vector Search

HNSW index for approximate nearest neighbor search with logarithmic complexity. Optional native acceleration is available.

    docs.build_hnsw_index(dim=128)
    docs.vector_search_hnsw([0.9, 0.1, 0.0], top_k=5)

### Columnar Analytics

Column-oriented storage for fast aggregation on large datasets.

    cs = users.columnar()
    cs.sum("age")
    cs.group_by("city")

### Hybrid Search

BM25 keyword matching combined with vector semantic similarity.

    docs.build_hybrid_index(text_field="title")
    docs.hybrid_search(query="python", query_vector=[0.9, 0.1], top_k=5)

### Change Data Capture

Real-time event stream for insert, update, and delete operations.

    db.on_change(lambda event: print(event.op, event.collection))

### Time-Series Storage

Timestamped metrics with retention policies and downsampling.

    ts = db.timeseries()
    ts.write("cpu", 45.5)
    ts.avg("cpu", last="5m")

### Distributed Features

- Replication: primary-replica synchronization over socket
- Sharding: hash-based distribution across multiple data directories
- Multi-Writer: optimistic locking with compare-and-swap

## Transactions and Concurrency

- Atomic commit and rollback
- Savepoints for nested operations
- Batch mode for high-speed bulk inserts
- Optimistic locking with compare-and-swap
- Per-record write locks
- File locking for multi-process safety

## Security

- XOR stream cipher with HMAC-SHA256 authentication
- PBKDF2 password hashing with 100,000 iterations
- HTTP token authentication with role-based access control
- Integrity verification

## Observability

- Structured JSON logging
- Query history
- Slow query log
- Metrics collector reporting p50, p95, and p99 latencies
- Safety report with RAM estimates

## Interfaces

- Python API
- SQL
- HTTP REST API
- Interactive shell with password authentication
- Command-line interface
- Async wrapper for bot and web frameworks

## Installation

Copy the package into a project directory:

    cp -r rayzorgendb /path/to/project/

Or install from source:

    git clone https://github.com/riza-del/rayzorgendb.git
    cd rayzorgendb
    pip install -e .

Requirements: Python 3.8 or newer. No third-party packages required.

Optional native acceleration:

    cd rayzorgendb/native
    cargo build --release

The native library is detected automatically when present. Otherwise, the pure Python implementation is used.

## Usage

### Basic Operations

    from rayzorgendb import RayzorgenDB

    db = RayzorgenDB()
    users = db.collection("users")

    rec = users.insert({"name": "Budi", "age": 25})
    users.get(rec.id)
    users.update(rec.id, {"age": 26})
    users.delete(rec.id)
    db.close()

### Query Builder

    users.query() .where("age", "gt", 20) .order_by("age", desc=True) .limit(10) .all()

Operators: eq, ne, gt, lt, gte, lte, in, nin, contains, icontains, startswith, endswith, regex, exists, between

### SQL

    db.execute("CREATE TABLE users (name TEXT, age INT)")
    db.execute("INSERT INTO users VALUES ('Budi', 25)")
    db.query_sql("SELECT * FROM users WHERE age > 20")
    db.query_sql("SELECT city, COUNT(*) FROM users GROUP BY city")

### Batch Insert

    db.begin_batch()
    for i in range(100000):
        users.insert({"name": "user" + str(i), "age": i % 50})
    db.end_batch()

### Async API

    from rayzorgendb.async_api.wrapper import AsyncDB

    db = AsyncDB()
    users = db.collection("users")
    await users.insert({"name": "Budi"})

## HTTP REST API

Start the server:

    python -m rayzorgendb.http.server

Example requests:

    curl http://localhost:9000/health
    curl -X POST http://localhost:9000/users -H "Content-Type: application/json" -d '{"name": "Budi", "age": 25}'

## Interactive Shell

    rayzorgen

    rayzorgen> create users
    rayzorgen> insert users name=Budi,age=25
    rayzorgen> show users
    rayzorgen> filter users age gt 24
    rayzorgen> sql SELECT * FROM users WHERE age > 25
    rayzorgen> exit

The shell requires authentication. Password hash is stored at ~/.rayzorgen/config.json.

## Performance

Benchmarks on Python 3.11, 1,000 records loaded, 500 operations per workload.

| Workload | Description | Throughput | p99 latency |
|----------|-------------|-----------|-------------|
| Read-only | 100% read | 60,166 ops/s | 0.024 ms |
| Mixed | 95% read, 5% update | 14,240 ops/s | 1.23 ms |
| Insert-heavy | 95% read, 5% insert | 13,859 ops/s | 1.13 ms |
| Write-heavy | 50% read, 50% update | 1,656 ops/s | 1.92 ms |

Additional metrics:

- Batch insert: 8,000 to 15,000 records per second
- Compression ratio: 82 percent
- Storage per record: 40 bytes on disk
- RAM per record (large mode): 200 bytes
- Capacity: approximately 1,000,000 records with 4 GB RAM

## Architecture

    Interfaces: Python API, SQL, HTTP REST, Shell, CLI, Async
                            |
                        Core Engine
                            |
        Storage | Query Planner | Advanced Engines
                            |
                Disk (.rdb + .wal)

The Smart layer (db.smart) provides a unified advanced interface: DAG branching, scored queries, reactive links, and simple verbs.

## Limitations

- Maximum practical size: approximately 2,000,000 records
- Single writer per database instance
- No network-native clustering
- Encryption uses XOR with HMAC, not AES

For high-concurrency server workloads or terabyte-scale datasets, a database system designed for that scale is required.

## Testing

    python -m unittest discover tests

200 automated tests across 13 files covering storage, codec, compression, checksum, multi-process locking, joins, time travel, vector search, columnar aggregation, hybrid search, SQL parsing, encryption, replication, sharding, CDC, and time-series.

## License

MIT License.
