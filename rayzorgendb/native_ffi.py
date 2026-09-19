"""
RayzorgenDB Native FFI

Uses ctypes to call the Rust .so library.
Falls back to pure Python if .so not available.

The .so is built with:
    cd rayzorgendb/native
    cargo build --release

Usage:
    from rayzorgendb.native_ffi import (
        cosine_similarity, cosine_batch, cosine_topk,
    )
"""

import math
import os
import ctypes
from typing import List, Tuple


NATIVE_AVAILABLE = False
_lib = None


# Search paths for the .so
_SO_PATHS = [
    os.path.join(os.path.dirname(__file__),
                 "native", "target", "release",
                 "librayzorgen_native.so"),
    os.path.join(os.path.dirname(__file__),
                 "native", "target", "debug",
                 "librayzorgen_native.so"),
    "./librayzorgen_native.so",
]


def _load_native():
    """Try to load the .so library."""
    global _lib, NATIVE_AVAILABLE
    for path in _SO_PATHS:
        if os.path.exists(path):
            try:
                lib = ctypes.CDLL(path)
                # Set argtypes
                lib.cosine_similarity.argtypes = [
                    ctypes.POINTER(ctypes.c_double),
                    ctypes.c_size_t,
                    ctypes.POINTER(ctypes.c_double),
                    ctypes.c_size_t,
                ]
                lib.cosine_similarity.restype = ctypes.c_double

                lib.cosine_distance.argtypes = [
                    ctypes.POINTER(ctypes.c_double),
                    ctypes.c_size_t,
                    ctypes.POINTER(ctypes.c_double),
                    ctypes.c_size_t,
                ]
                lib.cosine_distance.restype = ctypes.c_double

                lib.cosine_batch.argtypes = [
                    ctypes.POINTER(ctypes.c_double),
                    ctypes.c_size_t,
                    ctypes.POINTER(ctypes.c_double),
                    ctypes.c_size_t,
                    ctypes.c_size_t,
                    ctypes.POINTER(ctypes.c_double),
                ]
                lib.cosine_batch.restype = ctypes.c_int

                lib.euclidean_distance.argtypes = [
                    ctypes.POINTER(ctypes.c_double),
                    ctypes.c_size_t,
                    ctypes.POINTER(ctypes.c_double),
                    ctypes.c_size_t,
                ]
                lib.euclidean_distance.restype = ctypes.c_double

                lib.sum_f64.argtypes = [
                    ctypes.POINTER(ctypes.c_double),
                    ctypes.c_size_t,
                ]
                lib.sum_f64.restype = ctypes.c_double

                _lib = lib
                NATIVE_AVAILABLE = True
                return True
            except (OSError, AttributeError):
                continue
    return False


_load_native()


# ============================================================
# Helpers
# ============================================================

def _to_c_array(values):
    """Convert Python list to C double array."""
    arr = (ctypes.c_double * len(values))(*values)
    return arr


# ============================================================
# Native implementations (if available)
# ============================================================

if NATIVE_AVAILABLE:
    def cosine_similarity(a, b):
        if not a or not b or len(a) != len(b):
            return 0.0
        arr_a = _to_c_array(a)
        arr_b = _to_c_array(b)
        return _lib.cosine_similarity(arr_a, len(a), arr_b, len(b))

    def cosine_distance(a, b):
        if not a or not b or len(a) != len(b):
            return 1.0
        arr_a = _to_c_array(a)
        arr_b = _to_c_array(b)
        return _lib.cosine_distance(arr_a, len(a), arr_b, len(b))

    def cosine_batch(query, vectors):
        if not query or not vectors:
            return []
        dim = len(query)
        n = len(vectors)
        # Flatten vectors
        flat = []
        valid_indices = []
        for i, v in enumerate(vectors):
            if isinstance(v, list) and len(v) == dim:
                flat.extend(v)
                valid_indices.append(i)
        if not flat:
            return [0.0] * n

        q_arr = _to_c_array(query)
        v_arr = (ctypes.c_double * len(flat))(*flat)
        out_arr = (ctypes.c_double * len(valid_indices))()
        rc = _lib.cosine_batch(
            q_arr, dim,
            v_arr, len(valid_indices), len(flat),
            out_arr,
        )
        # Map back
        result = [0.0] * n
        for idx, orig_i in enumerate(valid_indices):
            result[orig_i] = out_arr[idx]
        return result

    def euclidean_distance(a, b):
        if not a or not b or len(a) != len(b):
            return float("inf")
        arr_a = _to_c_array(a)
        arr_b = _to_c_array(b)
        return _lib.euclidean_distance(arr_a, len(a), arr_b, len(b))

    def sum_f64(values):
        if not values:
            return 0.0
        arr = _to_c_array(values)
        return _lib.sum_f64(arr, len(values))

else:
    # Python fallbacks
    def cosine_similarity(a, b):
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = 0.0
        na = 0.0
        nb = 0.0
        for i in range(len(a)):
            dot += a[i] * b[i]
            na += a[i] * a[i]
            nb += b[i] * b[i]
        if na == 0 or nb == 0:
            return 0.0
        sim = dot / (math.sqrt(na) * math.sqrt(nb))
        return max(-1.0, min(1.0, sim))

    def cosine_distance(a, b):
        return 1.0 - cosine_similarity(a, b)

    def cosine_batch(query, vectors):
        return [cosine_similarity(query, v) for v in vectors]

    def euclidean_distance(a, b):
        if len(a) != len(b):
            return float("inf")
        total = 0.0
        for i in range(len(a)):
            d = a[i] - b[i]
            total += d * d
        return math.sqrt(total)

    def sum_f64(values):
        return float(sum(values))


# ============================================================
# Top-K (built on cosine_batch)
# ============================================================

def cosine_topk(query, vectors, k):
    """Return [(index, score), ...] sorted desc."""
    scores = cosine_batch(query, vectors)
    indexed = list(enumerate(scores))
    indexed.sort(key=lambda x: x[1], reverse=True)
    return indexed[:k]


def info() -> dict:
    return {
        "native_available": NATIVE_AVAILABLE,
        "backend": "rust" if NATIVE_AVAILABLE else "python",
    }


__all__ = [
    "cosine_similarity", "cosine_distance",
    "cosine_batch", "cosine_topk",
    "euclidean_distance", "sum_f64",
    "info", "NATIVE_AVAILABLE",
]
