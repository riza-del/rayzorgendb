"""
RayzorgenDB WAL
Write-Ahead Log — semua operasi ditulis dulu ke log
sebelum ke snapshot. Kalau crash, pulihkan dari log.
"""

import os
import struct
import threading
import time
from typing import List, Tuple

from rayzorgendb.storage.binary.codec import BinaryCodec


# Format record WAL:
# [4 byte len][8 byte timestamp][1 byte op][8 byte key_len][key bytes][payload]
# op: 0 = insert, 1 = update, 2 = delete


class WAL:
    """Write-Ahead Log untuk satu koleksi"""
    
    OP_INSERT = 0
    OP_UPDATE = 1
    OP_DELETE = 2
    
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.RLock()
        self._file = None
        self._sync_fsync = False  # default OFF (buffer mode)
        self._buffer = []
        self._buffer_size = 0
        self._buffer_max = 1000
        self._open()
    
    def _open(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._file = open(self.path, "ab")
    
    def append(self, op: int, key: str, payload=None):
        """Tulis 1 operasi ke WAL"""
        with self._lock:
            if self._file is None:
                return
            key_bytes = key.encode("utf-8")
            body = struct.pack(
                ">d", time.time()
            ) + bytes([op]) + struct.pack(
                ">I", len(key_bytes)
            ) + key_bytes
            
            if payload is not None:
                body += BinaryCodec.encode(payload)
            
            rec = struct.pack(">I", len(body)) + body

            # Buffer dulu (kalau tidak sync_fsync)
            if not self._sync_fsync:
                self._buffer.append(rec)
                self._buffer_size += 1
                if self._buffer_size >= self._buffer_max:
                    self._flush_buffer()
                return

            # Sync mode: write langsung
            try:
                self._file.write(rec)
                self._file.flush()
                os.fsync(self._file.fileno())
            except (IOError, OSError):
                pass

    def _flush_buffer(self):
        """Tulis buffer ke disk sekaligus."""
        with self._lock:
            if not self._buffer or self._file is None:
                return
            try:
                for rec in self._buffer:
                    self._file.write(rec)
                self._file.flush()
                self._buffer.clear()
                self._buffer_size = 0
            except (IOError, OSError):
                pass

    def flush(self):
        """Public: paksa flush buffer ke disk."""
        self._flush_buffer()
    
    def read_all(self) -> List[Tuple[float, int, str, any]]:
        """Baca semua entri WAL"""
        if not os.path.exists(self.path):
            return []
        entries = []
        try:
            with open(self.path, "rb") as f:
                data = f.read()
        except IOError:
            return []
        
        off = 0
        while off < len(data):
            if off + 4 > len(data):
                break
            try:
                body_len = struct.unpack_from(">I", data, off)[0]
                off += 4
                if off + body_len > len(data):
                    break  # record tidak lengkap (crash)
                body = data[off:off + body_len]
                off += body_len
                
                ts = struct.unpack_from(">d", body, 0)[0]
                op = body[8]
                klen = struct.unpack_from(">I", body, 9)[0]
                key = body[13:13 + klen].decode("utf-8")
                rest = body[13 + klen:]
                
                payload = None
                if rest:
                    payload, _ = BinaryCodec.decode(rest, 0)
                
                entries.append((ts, op, key, payload))
            except (struct.error, ValueError, UnicodeDecodeError):
                break  # stop kalau corrupt
        return entries
    
    def rotate(self):
        self._flush_buffer()
        """Ganti WAL setelah snapshot — kosongkan log"""
        with self._lock:
            if self._file:
                try:
                    self._file.close()
                except Exception:
                    pass
            try:
                if os.path.exists(self.path):
                    os.remove(self.path)
            except OSError:
                pass
            self._open()
    
    def close(self):
        self._flush_buffer()
        with self._lock:
            if self._file:
                try:
                    self._file.close()
                except Exception:
                    pass
                self._file = None

    def set_sync_mode(self, enabled: bool):
        """
        Enable/disable fsync per write.
        Disable for batch mode (faster, less durable).
        """
        self._sync_fsync = enabled

    def flush(self):
        """Force flush to disk."""
        with self._lock:
            if self._file:
                try:
                    self._file.flush()
                    os.fsync(self._file.fileno())
                except (IOError, OSError):
                    pass
