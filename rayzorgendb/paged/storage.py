"""
RayzorgenDB Paged Storage

Page-based disk storage with LRU cache.
Similar to SQLite pages but for our binary format.

Page size: 4096 bytes (4 KB)
Cache: LRU up to N pages (default 256 = 1 MB)

Handles data larger than RAM.
"""

import os
import struct
import threading
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional


PAGE_SIZE = 4096
MAGIC = b"RPAG"
HEADER_SIZE = 16  # magic(4) + version(2) + flags(2) + size(4) + count(4)


class Page:
    """Single page."""

    __slots__ = ("page_id", "data", "dirty", "last_used")

    def __init__(self, page_id: int, data: bytes = None):
        self.page_id = page_id
        self.data = data or b""
        self.dirty = False
        self.last_used = time.time()

    def size(self) -> int:
        return len(self.data)


class PageCache:
    """LRU cache for pages."""

    def __init__(self, max_pages: int = 256):
        self.max_pages = max_pages
        self._cache: OrderedDict = OrderedDict()
        self._lock = threading.RLock()
        self.hits = 0
        self.misses = 0
        self.evictions = 0

    def get(self, page_id: int) -> Optional[Page]:
        with self._lock:
            page = self._cache.get(page_id)
            if page is not None:
                page.last_used = time.time()
                self._cache.move_to_end(page_id)
                self.hits += 1
                return page
            self.misses += 1
            return None

    def put(self, page: Page):
        with self._lock:
            if page.page_id in self._cache:
                del self._cache[page.page_id]
            self._cache[page.page_id] = page
            while len(self._cache) > self.max_pages:
                old_id, old_page = self._cache.popitem(last=False)
                self.evictions += 1

    def remove(self, page_id: int):
        with self._lock:
            self._cache.pop(page_id, None)

    def all_dirty(self) -> List[Page]:
        with self._lock:
            return [
                p for p in self._cache.values() if p.dirty
            ]

    def clear(self):
        with self._lock:
            self._cache.clear()

    def stats(self) -> Dict:
        with self._lock:
            total = self.hits + self.misses
            ratio = self.hits / total if total > 0 else 0
            return {
                "size": len(self._cache),
                "max_pages": self.max_pages,
                "hits": self.hits,
                "misses": self.misses,
                "evictions": self.evictions,
                "hit_ratio": round(ratio, 4),
            }


class PagedStorage:
    """
    Disk-based page storage.

    Layout:
        [header: 16 bytes]
        [page 0: 4096 bytes]
        [page 1: 4096 bytes]
        ...
        [page N]

    Each page:
        - magic "RPAG" (4 bytes)
        - version (2 bytes)
        - flags (2 bytes)
        - payload size (4 bytes)
        - record count (4 bytes)
        - payload (variable)
    """

    def __init__(self, path: str, cache_pages: int = 256):
        self.path = path
        self.cache = PageCache(max_pages=cache_pages)
        self._lock = threading.RLock()
        self._file = None
        self._next_page = 0
        self._free_pages: List[int] = []

        os.makedirs(
            os.path.dirname(path) or ".", exist_ok=True
        )
        self._open()

    def _open(self):
        if os.path.exists(self.path):
            self._file = open(self.path, "r+b")
            self._load_header()
        else:
            self._file = open(self.path, "w+b")
            self._write_header()

    def _load_header(self):
        self._file.seek(0)
        header = self._file.read(HEADER_SIZE)
        if len(header) < HEADER_SIZE or header[:4] != MAGIC:
            # Corrupt, reset
            self._file.seek(0)
            self._write_header()
            return
        version = struct.unpack(">H", header[4:6])[0]
        flags = struct.unpack(">H", header[6:8])[0]
        size = struct.unpack(">I", header[8:12])[0]
        count = struct.unpack(">I", header[12:16])[0]
        self._next_page = count

    def _write_header(self):
        self._file.seek(0)
        header = (
            MAGIC
            + struct.pack(">H", 1)  # version
            + struct.pack(">H", 0)  # flags
            + struct.pack(">I", 0)  # size
            + struct.pack(">I", self._next_page)
        )
        self._file.write(header)
        self._file.flush()

    # --------------------------------------------------------
    # Page I/O
    # --------------------------------------------------------

    def read_page(self, page_id: int) -> Optional[Page]:
        """Read page from cache or disk."""
        with self._lock:
            # Try cache
            page = self.cache.get(page_id)
            if page is not None:
                return page

            # Read from disk
            offset = HEADER_SIZE + page_id * PAGE_SIZE
            try:
                self._file.seek(offset)
                data = self._file.read(PAGE_SIZE)
            except (IOError, OSError):
                return None

            if not data:
                return None

            page = Page(page_id, data)
            self.cache.put(page)
            return page

    def write_page(self, page: Page):
        """Write page to disk."""
        with self._lock:
            # Update next_page if writing beyond
            if page.page_id >= self._next_page:
                self._next_page = page.page_id + 1
                self._write_header()
            # Pad to PAGE_SIZE
            data = page.data
            if len(data) < PAGE_SIZE:
                data = data + b"\x00" * (
                    PAGE_SIZE - len(data)
                )
            elif len(data) > PAGE_SIZE:
                raise ValueError("Page too large")

            offset = HEADER_SIZE + page.page_id * PAGE_SIZE
            self._file.seek(offset)
            self._file.write(data)
            self._file.flush()
            page.dirty = False
            self.cache.put(page)

    def allocate_page(self) -> int:
        """Get a new page ID."""
        with self._lock:
            if self._free_pages:
                return self._free_pages.pop()
            page_id = self._next_page
            self._next_page += 1
            self._write_header()
            return page_id

    def free_page(self, page_id: int):
        """Mark page as free."""
        with self._lock:
            self._free_pages.append(page_id)
            self.cache.remove(page_id)

    # --------------------------------------------------------
    # Record Storage
    # --------------------------------------------------------

    def pack_record(self, data: bytes) -> bytes:
        """Pack bytes with length prefix."""
        return struct.pack(">I", len(data)) + data

    def unpack_records(self, data: bytes) -> List[bytes]:
        """Extract all records from page payload."""
        records = []
        pos = 0
        while pos + 4 <= len(data):
            size = struct.unpack(">I", data[pos:pos+4])[0]
            pos += 4
            if size == 0 or pos + size > len(data):
                break
            records.append(data[pos:pos+size])
            pos += size
        return records

    def write_page_records(self, page_id: int,
                           records: List[bytes]):
        """Write list of records to page."""
        payload = b"".join(
            self.pack_record(r) for r in records
        )
        page = Page(page_id, payload)
        self.write_page(page)

    def read_page_records(self, page_id: int) -> List[bytes]:
        """Read records from page."""
        page = self.read_page(page_id)
        if page is None:
            return []
        return self.unpack_records(page.data)

    # --------------------------------------------------------
    # Flush & Maintenance
    # --------------------------------------------------------

    def flush(self):
        """Write all dirty pages to disk."""
        with self._lock:
            for page in self.cache.all_dirty():
                self.write_page(page)
            if self._file:
                try:
                    os.fsync(self._file.fileno())
                except (IOError, OSError):
                    pass

    def close(self):
        with self._lock:
            self.flush()
            if self._file:
                try:
                    self._file.close()
                except Exception:
                    pass
                self._file = None

    def stats(self) -> Dict:
        try:
            size = os.path.getsize(self.path)
        except OSError:
            size = 0
        return {
            "path": self.path,
            "pages": self._next_page,
            "file_size_mb": round(size / 1024 / 1024, 2),
            "page_size": PAGE_SIZE,
            "cache": self.cache.stats(),
        }


__all__ = [
    "PagedStorage", "Page", "PageCache",
    "PAGE_SIZE", "MAGIC",
]
