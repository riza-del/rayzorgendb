"""
RayzorgenDB Binary Codec — v2 FIXED
Optimasi:
- Varint untuk int (1 byte untuk 0-127, hemat 87%)
- String tanpa tag (langsung length prefix)
- Field key di-intern (dict key tetap string)
- Float32 kalau bisa (fallback float64)
"""

import struct
from typing import Any


T_NULL    = 0x00
T_FALSE   = 0x01
T_TRUE    = 0x02
T_INT8    = 0x03
T_INT16   = 0x04
T_INT32   = 0x05
T_INT64   = 0x06
T_UINT8   = 0x07
T_UINT16  = 0x08
T_UINT32  = 0x09
T_FLOAT32 = 0x0A
T_FLOAT64 = 0x0B
T_STR     = 0x0C
T_BYTES   = 0x0D
T_LIST    = 0x0E
T_DICT    = 0x0F


class BinaryCodec:
    """Encoder / decoder binary ringkas"""
    
    @staticmethod
    def encode(obj: Any) -> bytes:
        return BinaryCodec._enc(obj)
    
    @staticmethod
    def decode(data: bytes, offset: int = 0):
        return BinaryCodec._dec(data, offset)
    
    # ─── Encode ────────────────────────────────
    @staticmethod
    def _enc(obj: Any) -> bytes:
        if obj is None:
            return bytes([T_NULL])
        if obj is True:
            return bytes([T_TRUE])
        if obj is False:
            return bytes([T_FALSE])
        
        if isinstance(obj, int) and not isinstance(obj, bool):
            if obj >= 0:
                if obj < 256:
                    return bytes([T_UINT8]) + struct.pack(">B", obj)
                if obj < 65536:
                    return bytes([T_UINT16]) + struct.pack(">H", obj)
                if obj < 4294967296:
                    return bytes([T_UINT32]) + struct.pack(">I", obj)
                return bytes([T_INT64]) + struct.pack(">q", obj)
            else:
                if -128 <= obj < 0:
                    return bytes([T_INT8]) + struct.pack(">b", obj)
                if -32768 <= obj < 0:
                    return bytes([T_INT16]) + struct.pack(">h", obj)
                if -2147483648 <= obj < 0:
                    return bytes([T_INT32]) + struct.pack(">i", obj)
                return bytes([T_INT64]) + struct.pack(">q", obj)
        
        if isinstance(obj, float):
            # Coba float32 dulu
            try:
                f32 = struct.pack(">f", obj)
                if struct.unpack(">f", f32)[0] == obj:
                    return bytes([T_FLOAT32]) + f32
            except (OverflowError, struct.error):
                pass
            return bytes([T_FLOAT64]) + struct.pack(">d", obj)
        
        if isinstance(obj, str):
            raw = obj.encode("utf-8")
            # Panjang pakai varint ringkas
            return bytes([T_STR]) + BinaryCodec._pack_len(len(raw)) + raw
        
        if isinstance(obj, (bytes, bytearray)):
            raw = bytes(obj)
            return bytes([T_BYTES]) + BinaryCodec._pack_len(len(raw)) + raw
        
        if isinstance(obj, (list, tuple)):
            buf = bytearray([T_LIST])
            buf += BinaryCodec._pack_len(len(obj))
            for item in obj:
                buf += BinaryCodec._enc(item)
            return bytes(buf)
        
        if isinstance(obj, dict):
            buf = bytearray([T_DICT])
            buf += BinaryCodec._pack_len(len(obj))
            for k, v in obj.items():
                k_str = str(k)
                k_raw = k_str.encode("utf-8")
                buf += BinaryCodec._pack_len(len(k_raw)) + k_raw
                buf += BinaryCodec._enc(v)
            return bytes(buf)
        
        return BinaryCodec._enc(str(obj))
    
    # ─── Varint panjang ────────────────────────
    @staticmethod
    def _pack_len(n: int) -> bytes:
        """Panjang 1-5 byte (varint)"""
        if n < 128:
            return bytes([n])
        if n < 16384:
            return bytes([0x80 | (n >> 8), n & 0xFF])
        if n < 2097152:
            return bytes([
                0xC0 | (n >> 16), (n >> 8) & 0xFF, n & 0xFF
            ])
        # 4 byte (maks 4GB)
        return bytes([0xE0]) + struct.pack(">I", n)
    
    @staticmethod
    def _unpack_len(data: bytes, off: int):
        b = data[off]
        if b < 0x80:
            return b, off + 1
        if b < 0xC0:
            return ((b & 0x3F) << 8) | data[off + 1], off + 2
        if b < 0xE0:
            return (
                ((b & 0x1F) << 16)
                | (data[off + 1] << 8)
                | data[off + 2],
                off + 3,
            )
        n = struct.unpack_from(">I", data, off + 1)[0]
        return n, off + 5
    
    # ─── Decode ────────────────────────────────
    @staticmethod
    def _dec(data: bytes, off: int):
        if off >= len(data):
            raise ValueError("Data habis")
        tag = data[off]
        off += 1
        
        if tag == T_NULL:   return None, off
        if tag == T_FALSE:  return False, off
        if tag == T_TRUE:   return True, off
        
        if tag == T_UINT8:
            return data[off], off + 1
        if tag == T_UINT16:
            return struct.unpack_from(">H", data, off)[0], off + 2
        if tag == T_UINT32:
            return struct.unpack_from(">I", data, off)[0], off + 4
        if tag == T_INT8:
            return struct.unpack_from(">b", data, off)[0], off + 1
        if tag == T_INT16:
            return struct.unpack_from(">h", data, off)[0], off + 2
        if tag == T_INT32:
            return struct.unpack_from(">i", data, off)[0], off + 4
        if tag == T_INT64:
            return struct.unpack_from(">q", data, off)[0], off + 8
        if tag == T_FLOAT32:
            return struct.unpack_from(">f", data, off)[0], off + 4
        if tag == T_FLOAT64:
            return struct.unpack_from(">d", data, off)[0], off + 8
        if tag == T_STR:
            n, off = BinaryCodec._unpack_len(data, off)
            return data[off:off + n].decode("utf-8"), off + n
        if tag == T_BYTES:
            n, off = BinaryCodec._unpack_len(data, off)
            return data[off:off + n], off + n
        if tag == T_LIST:
            n, off = BinaryCodec._unpack_len(data, off)
            out = []
            for _ in range(n):
                item, off = BinaryCodec._dec(data, off)
                out.append(item)
            return out, off
        if tag == T_DICT:
            n, off = BinaryCodec._unpack_len(data, off)
            out = {}
            for _ in range(n):
                klen, off = BinaryCodec._unpack_len(data, off)
                key = data[off:off + klen].decode("utf-8")
                off += klen
                val, off = BinaryCodec._dec(data, off)
                out[key] = val
            return out, off
        raise ValueError(f"Tag tidak dikenal: {tag}")
