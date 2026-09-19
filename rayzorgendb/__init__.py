"""
RayzorgenDB
Database embedded multi-engine. Python + Rust. Gratis.

Fitur utama:
- Multi-model: document, key-value, vector, relational
- Time travel (history, snapshot, restore)
- Vector search (HNSW, cosine)
- Columnar analytics
- Hybrid search (BM25 + vector)
- SQL native
- JOIN antar koleksi
- Transaction + batch mode
- Kompresi 82%, enkripsi, WAL
- HTTP API, shell interaktif
- Async support untuk bot Telegram
- Zero dependency (100% stdlib)

Quick start:
    from rayzorgendb import RayzorgenDB

    db = RayzorgenDB()
    users = db.collection("users")
    users.insert({"nama": "Budi", "umur": 25})
    users.query().where("umur", "gt", 20).all()

SQL:
    db.execute("INSERT INTO users VALUES ('Siti', 30)")
    db.query_sql("SELECT * FROM users WHERE umur > 25")
"""

from rayzorgendb.api import (
    RayzorgenDB, Collection, Transaction, Record,
)
from rayzorgendb.config import Config, DEFAULT_CONFIG

__version__ = "2.0.0"

__all__ = [
    "RayzorgenDB",
    "Collection",
    "Transaction",
    "Record",
    "Config",
    "DEFAULT_CONFIG",
]
