# RayzorgenDB

Embedded local database. Instant, clean, ready to use.

Forget the complexity of managing a database server, the overhead of cloud configuration, or the burden of dependency installation.

RayzorgenDB is a Python-based data storage solution engineered for maximum efficiency. Import it into your code and the database operates autonomously on your local device.

## Core Advantages

- **Instant Deployment** - No setup time. Integrate directly into your code without initial configuration.
- **Standalone Architecture** - Runs entirely on local hardware. No external services, no centralized servers, no internet connection required.
- **Lightweight and Clean** - Built with Python for optimal performance. Keeps your project free from bloatware.
- **Built for Developers** - Designed for those who want to focus purely on application logic, not infrastructure.

## Features

### Storage
- Custom binary format with varint encoding
- Write-Ahead Log with crash recovery
- zlib compression (82 percent size reduction)
- CRC32 checksum verification
- Paged disk storage

### Query
- Native SQL (SELECT, INSERT, UPDATE, DELETE, JOIN)
- Chainable Python query builder
- Cost-based optimizer
- EXPLAIN and ANALYZE
- Full-text search
- Aggregations: SUM, AVG, MIN, MAX, COUNT
- GROUP BY, HAVING, DISTINCT

### Indexes
- Hash indexes for equality lookups
- B+ Tree indexes for range queries
- Prefix search
- Automatic index selection

### Relational
- INNER, LEFT, RIGHT JOIN
- Multi-collection chains
- Nested field access

### Time Travel
- Full version history per record
- Point-in-time snapshots
- Version diff
- Restore to any previous version

### Vector Search
- HNSW index with O(log n) complexity
- Cosine and Euclidean distance
- Optional Rust acceleration

### Analytics
- Columnar engine
- Hybrid search (BM25 plus vector)
- Time-series storage

### Change Data Capture
- Real-time event stream
- Filters and replay

### Transactions
- Atomic commit and rollback
- Savepoints
- Batch mode

### Concurrency
- Multi-writer with optimistic locking
- Compare-and-swap
- Per-record write locks

### Distribution
- Replication
- Sharding
- CDC stream

### Security
- XOR cipher with HMAC-SHA256
- PBKDF2 password hashing
- HTTP token authentication

### Interfaces
- Python API
- SQL
- HTTP REST API
- Interactive shell
- Command-line interface
- Async wrapper

## Installation

Copy the folder:

    cp -r rayzorgendb /path/to/project/

Install from source:

    git clone https://github.com/riza-del/rayzorgendb.git
    cd rayzorgendb
    pip install -e .

Requirements: Python 3.8 or newer.

Optional Rust acceleration:

    cd rayzorgendb/native
    cargo build --release

## Quick Start

Basic CRUD:

    from rayzorgendb import RayzorgenDB

    db = RayzorgenDB()
    users = db.collection("users")

    rec = users.insert({"name": "Budi", "age": 25})
    users.get(rec.id)
    users.update(rec.id, {"age": 26})
    users.delete(rec.id)
    db.close()

Chainable Query:

    users.query() .where("age", "gt", 20) .order_by("age", desc=True) .limit(10) .all()

Operators: eq, ne, gt, lt, gte, lte, in, nin, contains, icontains, startswith, endswith, regex, exists, between

SQL:

    db.execute("CREATE TABLE users (name TEXT, age INT)")
    db.execute("INSERT INTO users VALUES ('Budi', 25)")
    db.query_sql("SELECT * FROM users WHERE age > 20")
    db.query_sql("SELECT city, COUNT(*) FROM users GROUP BY city")

Indexes:

    users.create_index("email")
    users.create_sorted_index("age")
    users.find_by("email", "a@b.c")
    users.range("age", 20, 30)

Time Travel:

    users.history("record-id")
    users.at("2026-01-01").all()
    users.diff("record-id", 1, 3)
    users.restore_version("record-id", 1)

Vector Search:

    docs = db.collection("docs")
    docs.insert({"title": "Python tutorial", "_vector": [0.9, 0.1, 0.0]})
    docs.build_hnsw_index(dim=3)
    docs.vector_search_hnsw([1.0, 0.0, 0.0], top_k=5)

Transactions:

    tx = db.transaction()
    tx.insert("orders", {"total": 500})
    tx.commit()

Batch Insert:

    db.begin_batch()
    for i in range(100000):
        users.insert({"name": "user" + str(i), "age": i % 50})
    db.end_batch()

Async API:

    from rayzorgendb.async_api.wrapper import AsyncDB

    db = AsyncDB()
    users = db.collection("users")
    await users.insert({"name": "Budi"})

## Interactive Shell

    rayzorgen

    rayzorgen> create users
    rayzorgen> insert users name=Budi,age=25
    rayzorgen> show users
    rayzorgen> filter users age gt 24
    rayzorgen> sql SELECT * FROM users WHERE age > 25
    rayzorgen> exit

## HTTP REST API

    python -m rayzorgendb.http.server

    curl http://localhost:9000/health
    curl -X POST http://localhost:9000/users -H "Content-Type: application/json" -d '{"name": "Budi", "age": 25}'

## Performance (YCSB)

Tested on Android Termux, Python 3.11, 1000 records loaded, 500 operations per workload.

- Workload C (100 percent read): 60,166 ops per second
- Workload B (95 percent read, 5 percent update): 14,240 ops per second
- Workload D (95 percent read, 5 percent insert): 13,859 ops per second
- Workload A (50 percent read, 50 percent update): 1,656 ops per second

Additional metrics:

- Insert (batch mode): 8,000 to 15,000 records per second
- Compression ratio: 82 percent
- Storage per record: 40 bytes
- RAM per record (large mode): 200 bytes
- Maximum records (RAM 4 GB): 1,000,000

## Testing

    python -m unittest discover tests

200+ automated tests.

## License

MIT License.
