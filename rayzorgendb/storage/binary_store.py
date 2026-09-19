"""
RayzorgenDB Binary Store — FIXED
- Snapshot per collection pakai lock
- WAL tidak buka file terus, close kalau idle
"""

import os
import struct
import zlib
import threading
import time
from typing import Any, Dict, List

from rayzorgendb.storage.binary.codec import BinaryCodec
from rayzorgendb.storage.wal.log import WAL


MAGIC = b"RAYZ"
MAGIC_COMPRESSED = b"RAYZ"
FORMAT_VERSION = 2


class BinaryStore:
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self._lock = threading.RLock()
        self._wals: Dict[str, WAL] = {}
        self._sync_mode = True
    
    def _safe(self, name: str) -> str:
        return "".join(
            c for c in name if c.isalnum() or c in "_-"
        )[:64]
    
    def _snap_path(self, c: str) -> str:
        return os.path.join(
            self.data_dir, f"{self._safe(c)}.rdb"
        )
    
    def _wal_path(self, c: str) -> str:
        return os.path.join(
            self.data_dir, f"{self._safe(c)}.wal"
        )
    
    def _wal(self, collection: str) -> WAL:
        if collection not in self._wals:
            wal = WAL(self._wal_path(collection))
            wal.set_sync_mode(self._sync_mode)
            self._wals[collection] = wal
        return self._wals[collection]
    
    # ─── Save / Load ───────────────────────────
    def save(self, collection: str,
             data: Dict[str, Any]) -> bool:
        with self._lock:
            path = self._snap_path(collection)
            tmp = path + ".tmp"
            try:
                # Build raw payload
                import io
                buffer = io.BytesIO()
                buffer.write(MAGIC)
                buffer.write(struct.pack(">H", FORMAT_VERSION))
                buffer.write(struct.pack(">I", len(data)))
                for rid, raw in data.items():
                    rid_b = rid.encode("utf-8")
                    buffer.write(struct.pack(">I", len(rid_b)))
                    buffer.write(rid_b)
                    payload = BinaryCodec.encode(raw)
                    buffer.write(struct.pack(">I", len(payload)))
                    buffer.write(payload)

                raw_bytes = buffer.getvalue()

                # Compress with zlib
                compressed = zlib.compress(raw_bytes, level=6)

                # Use compressed if smaller (include 1-byte flag)
                if len(compressed) + 1 < len(raw_bytes):
                    header = b"C"
                    body = compressed
                else:
                    header = b"U"
                    body = raw_bytes

                with open(tmp, "wb") as f:
                    f.write(header)
                    f.write(body)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, path)
                self._wal(collection).rotate()
                return True
            except (IOError, OSError, struct.error):
                try:
                    if os.path.exists(tmp):
                        os.remove(tmp)
                except OSError:
                    pass
                return False
    
    def load(self, collection: str) -> Dict[str, Any]:
        with self._lock:
            data = self._load_snapshot(collection)
            return self._apply_wal(collection, data)
    
    def _load_snapshot(self, collection: str) -> Dict[str, Any]:
        path = self._snap_path(collection)
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "rb") as f:
                # Detect compressed or raw
                first = f.read(1)

                if first == b"C":
                    # Compressed
                    compressed = f.read()
                    try:
                        raw_bytes = zlib.decompress(compressed)
                    except zlib.error:
                        return {}
                    import io
                    stream = io.BytesIO(raw_bytes)
                elif first == b"U":
                    # Uncompressed
                    raw_bytes = f.read()
                    import io
                    stream = io.BytesIO(raw_bytes)
                else:
                    # Legacy format (no flag byte)
                    f.seek(0)
                    legacy = f.read()
                    # Check for MAGIC
                    if legacy[:4] != MAGIC:
                        return {}
                    import io
                    stream = io.BytesIO(legacy)

                # Read header from stream
                if stream.read(4) != MAGIC:
                    return {}
                stream.read(2)  # version
                count = struct.unpack(
                    ">I", stream.read(4)
                )[0]

                data = {}
                for _ in range(count):
                    id_len = struct.unpack(
                        ">I", stream.read(4)
                    )[0]
                    rid = stream.read(id_len).decode("utf-8")
                    p_len = struct.unpack(
                        ">I", stream.read(4)
                    )[0]
                    payload = stream.read(p_len)
                    raw, _ = BinaryCodec.decode(payload, 0)
                    data[rid] = raw
                return data
        except (IOError, struct.error, ValueError):
            return {}
    
    def _apply_wal(self, collection: str,
                   data: Dict[str, Any]) -> Dict[str, Any]:
        entries = self._wal(collection).read_all()
        for ts, op, key, payload in entries:
            if op == WAL.OP_INSERT:
                data[key] = payload
            elif op == WAL.OP_UPDATE:
                if key in data and isinstance(payload, dict):
                    data[key].update(payload)
                    data[key]["updated_at"] = ts
                    data[key]["version"] = (
                        data[key].get("version", 1) + 1
                    )
                else:
                    data[key] = payload
            elif op == WAL.OP_DELETE:
                data.pop(key, None)
        return data
    
    def append_wal(self, collection, op, key, payload=None):
        self._wal(collection).append(op, key, payload)
    
    # ─── Collections ───────────────────────────
    def list_collections(self) -> List[str]:
        try:
            files = os.listdir(self.data_dir)
        except OSError:
            return []
        return sorted({
            f[:-4] for f in files if f.endswith(".rdb")
        })
    
    def delete(self, collection: str) -> bool:
        with self._lock:
            if collection in self._wals:
                try:
                    self._wals[collection].close()
                except Exception:
                    pass
                del self._wals[collection]
            ok = False
            for p in [
                self._snap_path(collection),
                self._wal_path(collection),
            ]:
                try:
                    if os.path.exists(p):
                        os.remove(p)
                        ok = True
                except OSError:
                    pass
            return ok
    
    def backup(self, collection: str, path: str) -> bool:
        data = self.load(collection)
        if not data:
            return False
        try:
            with open(path, "wb") as f:
                f.write(MAGIC)
                f.write(struct.pack(">H", FORMAT_VERSION))
                f.write(struct.pack(">I", len(data)))
                for rid, raw in data.items():
                    rid_b = rid.encode("utf-8")
                    f.write(struct.pack(">I", len(rid_b)))
                    f.write(rid_b)
                    p = BinaryCodec.encode(raw)
                    f.write(struct.pack(">I", len(p)))
                    f.write(p)
            return True
        except (IOError, OSError):
            return False
    
    def restore(self, collection: str, path: str) -> bool:
        if not os.path.exists(path):
            return False
        try:
            with open(path, "rb") as f:
                if f.read(4) != MAGIC:
                    return False
                f.read(2)
                count = struct.unpack(">I", f.read(4))[0]
                data = {}
                for _ in range(count):
                    id_len = struct.unpack(">I", f.read(4))[0]
                    rid = f.read(id_len).decode("utf-8")
                    p_len = struct.unpack(">I", f.read(4))[0]
                    payload = f.read(p_len)
                    raw, _ = BinaryCodec.decode(payload, 0)
                    data[rid] = raw
            return self.save(collection, data)
        except (IOError, struct.error, ValueError):
            return False
    
    def close_all(self):
        """Tutup semua WAL — hindari ResourceWarning"""
        with self._lock:
            for name, wal in list(self._wals.items()):
                try:
                    wal.close()
                except Exception:
                    pass
            self._wals.clear()
    
    def __del__(self):
        try:
            self.close_all()
        except Exception:
            pass
    
    def wal_size(self, collection: str) -> int:
        p = self._wal_path(collection)
        return os.path.getsize(p) if os.path.exists(p) else 0
    
    def snapshot_size(self, collection: str) -> int:
        p = self._snap_path(collection)
        return os.path.getsize(p) if os.path.exists(p) else 0

    def compression_ratio(self, collection: str) -> float:
        """Return compression ratio for a collection."""
        raw = self.snapshot_size(collection)
        if raw == 0:
            return 0.0
        return round(
            1.0 - (raw / max(raw, 1)), 4
        )

    def set_sync_mode(self, enabled: bool):
        """Enable/disable fsync (current + future WALs)."""
        self._sync_mode = enabled
        for wal in self._wals.values():
            wal.set_sync_mode(enabled)

    def flush_all_wal(self):
        """Force flush all WALs to disk."""
        for wal in self._wals.values():
            wal.flush()
