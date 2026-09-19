"""
RayzorgenDB Stability Module

Auto-detect RAM, safe limits, chunked insert,
string interning, and RAM monitoring.
"""

import os
import sys
import time
import threading
from typing import Dict, List, Any, Callable


# ============================================================
# RAM Detection
# ============================================================

def get_ram_info() -> Dict:
    """Detect total and available RAM in MB."""
    info = {
        "total_mb": 0,
        "available_mb": 0,
        "used_mb": 0,
    }
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    info["total_mb"] = int(line.split()[1]) / 1024
                elif line.startswith("MemAvailable:"):
                    info["available_mb"] = int(line.split()[1]) / 1024
        info["used_mb"] = info["total_mb"] - info["available_mb"]
    except (IOError, OSError):
        pass
    return info


def get_process_ram_mb() -> float:
    """Get RAM used by current process in MB."""
    try:
        with open("/proc/self/status", "r") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
    except (IOError, OSError):
        pass
    return 0.0


def auto_choose_mode() -> str:
    """
    Choose mode based on available RAM.
    - large: if available RAM < 3 GB (heavy phones)
    - full: if available RAM >= 3 GB
    """
    info = get_ram_info()
    available = info.get("available_mb", 0)
    if available == 0:
        return "full"  # Can't detect, assume full
    if available < 3000:  # < 3 GB
        return "large"
    return "full"


# ============================================================
# String Interning
# ============================================================

def intern_value(value: Any) -> Any:
    """Intern strings recursively for memory savings."""
    if isinstance(value, str):
        return sys.intern(value) if len(value) < 100 else value
    if isinstance(value, dict):
        return {
            sys.intern(k) if isinstance(k, str) else k: intern_value(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [intern_value(x) for x in value]
    return value


# ============================================================
# RAM Monitor
# ============================================================

class RAMMonitor:
    """Monitor RAM usage, warn when approaching limit."""

    def __init__(self, min_free_mb: float = 300.0,
                 check_every: int = 5000):
        self.min_free_mb = min_free_mb
        self.check_every = check_every
        self._counter = 0
        self._start_ram = get_process_ram_mb()
        self._lock = threading.RLock()
        self.warned = False

    def check(self):
        """Check RAM; raise if below minimum."""
        with self._lock:
            self._counter += 1
            if self._counter % self.check_every != 0:
                return
            info = get_ram_info()
            free = info.get("available_mb", 0)
            if free > 0 and free < self.min_free_mb:
                raise MemoryError(
                    "RAM low: " + str(round(free, 0)) +
                    " MB free. Minimum: " +
                    str(self.min_free_mb) + " MB. "
                    "Use large mode or chunked insert."
                )

    def current_usage_mb(self) -> float:
        return get_process_ram_mb() - self._start_ram

    def reset(self):
        with self._lock:
            self._counter = 0
            self._start_ram = get_process_ram_mb()
            self.warned = False


# ============================================================
# Chunked Insert
# ============================================================

def insert_chunked(collection, items: List[Dict],
                    chunk_size: int = 10000,
                    on_progress: Callable = None,
                    check_ram: bool = True,
                    min_free_mb: float = 200.0):
    """
    Insert many records in chunks. Checkpoints between chunks.

    Args:
        collection: RayzorgenDB Collection
        items: list of dicts
        chunk_size: records per chunk (default 10000)
        on_progress: called every chunk with (done, total)
        check_ram: check RAM before each chunk
        min_free_mb: stop if free RAM below this

    Returns:
        list of created record IDs
    """
    db = collection.core
    total = len(items)
    inserted_ids = []
    monitor = RAMMonitor(min_free_mb=min_free_mb,
                          check_every=1) if check_ram else None

    for start in range(0, total, chunk_size):
        chunk = items[start:start + chunk_size]

        # RAM check
        if monitor is not None:
            info = get_ram_info()
            free = info.get("available_mb", 0)
            if free > 0 and free < min_free_mb:
                raise MemoryError(
                    "Stopping at record " + str(start) +
                    "/" + str(total) + ": RAM low (" +
                    str(round(free, 0)) + " MB free)."
                )

        # Insert chunk
        db.begin_batch()
        try:
            for item in chunk:
                rec = collection.insert(item)
                inserted_ids.append(rec.id)
        finally:
            db.end_batch()

        # Progress callback
        done = min(start + chunk_size, total)
        if on_progress:
            try:
                on_progress(done, total)
            except Exception:
                pass

    return inserted_ids


# ============================================================
# Safety API
# ============================================================

def estimate_max_records(avg_bytes: int = 600) -> int:
    """
    Estimate safe max records for this device.
    Keeps 30% RAM headroom.
    """
    info = get_ram_info()
    available = info.get("available_mb", 0)
    if available == 0:
        return 500000  # Default safe
    # Use 60% of available RAM
    usable_mb = available * 0.6
    usable_bytes = usable_mb * 1024 * 1024
    return int(usable_bytes / avg_bytes)


def print_safety_report():
    """Print device safety report."""
    info = get_ram_info()
    proc = get_process_ram_mb()
    mode = auto_choose_mode()
    max_rec = estimate_max_records()

    print("=" * 50)
    print("RAYZORGENDB SAFETY REPORT")
    print("=" * 50)
    print("RAM total      : " + str(round(info["total_mb"], 0)) + " MB")
    print("RAM available  : " + str(round(info["available_mb"], 0)) + " MB")
    print("RAM process    : " + str(round(proc, 1)) + " MB")
    print("Recommended    : " + mode + " mode")
    print("Max records    : " + "{:,}".format(max_rec))
    print("=" * 50)


__all__ = [
    "get_ram_info", "get_process_ram_mb",
    "auto_choose_mode", "intern_value",
    "RAMMonitor", "insert_chunked",
    "estimate_max_records", "print_safety_report",
]
