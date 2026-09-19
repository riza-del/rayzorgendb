"""
RayzorgenDB Lock Manager
Cross-process file locking for safe concurrent access.

Uses fcntl on Unix (Linux, macOS, Termux) and msvcrt on Windows.
"""

import os
import time
import threading
from typing import Optional


# Detect platform
try:
    import fcntl
    HAS_FCNTL = True
except ImportError:
    HAS_FCNTL = False

try:
    import msvcrt
    HAS_MSVCRT = True
except ImportError:
    HAS_MSVCRT = False


class LockTimeout(Exception):
    """Raised when a lock cannot be acquired within timeout."""
    pass


class FileLock:
    """
    Cross-process file lock.

    Usage:
        lock = FileLock("/path/to/lockfile")
        with lock.acquire(timeout=10):
            # critical section
            pass
    """

    def __init__(self, path: str):
        self.path = path
        self._file = None
        self._acquired = False
        self._local_lock = threading.RLock()

    def acquire(self, timeout: float = 30.0,
                poll_interval: float = 0.1) -> "FileLock":
        """
        Acquire the lock. Blocks until acquired or timeout.
        """
        # Local thread-level lock first
        self._local_lock.acquire()

        if self._acquired:
            return self

        os.makedirs(os.path.dirname(self.path), exist_ok=True)

        try:
            self._file = open(self.path, "a+")
        except IOError as e:
            self._local_lock.release()
            raise IOError(
                "Cannot open lock file: " + str(e)
            )

        deadline = time.time() + timeout

        while time.time() < deadline:
            if self._try_lock():
                self._acquired = True
                self._write_pid()
                return self
            time.sleep(poll_interval)

        try:
            self._file.close()
        except Exception:
            pass
        self._file = None
        self._local_lock.release()
        raise LockTimeout(
            "Could not acquire lock on " + self.path +
            " within " + str(timeout) + " seconds"
        )

    def _try_lock(self) -> bool:
        """Try to acquire lock non-blocking."""
        try:
            if HAS_FCNTL:
                fcntl.flock(
                    self._file.fileno(),
                    fcntl.LOCK_EX | fcntl.LOCK_NB,
                )
                return True
            elif HAS_MSVCRT:
                msvcrt.locking(
                    self._file.fileno(),
                    msvcrt.LK_NBLCK,
                    1,
                )
                return True
            else:
                return True
        except (IOError, OSError):
            return False

    def _write_pid(self):
        """Write current PID into lock file for diagnostics."""
        try:
            self._file.seek(0)
            self._file.truncate()
            self._file.write(str(os.getpid()))
            self._file.flush()
        except Exception:
            pass

    def release(self):
        """Release the lock."""
        if not self._acquired:
            try:
                self._local_lock.release()
            except RuntimeError:
                pass
            return

        try:
            if HAS_FCNTL and self._file:
                fcntl.flock(
                    self._file.fileno(), fcntl.LOCK_UN
                )
            elif HAS_MSVCRT and self._file:
                try:
                    msvcrt.locking(
                        self._file.fileno(), msvcrt.LK_UNLCK, 1
                    )
                except Exception:
                    pass
        except Exception:
            pass

        try:
            if self._file:
                self._file.close()
        except Exception:
            pass

        self._file = None
        self._acquired = False

        try:
            self._local_lock.release()
        except RuntimeError:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()

    def __del__(self):
        try:
            self.release()
        except Exception:
            pass


class LockManager:
    """
    Manages locks for database resources.
    Provides per-collection locks with a global lock.
    """

    def __init__(self, data_dir: str, timeout: float = 30.0):
        self.data_dir = data_dir
        self.timeout = timeout
        self._global_lock = FileLock(
            os.path.join(data_dir, ".global.lock")
        )
        self._collection_locks = {}
        self._lock_table = threading.RLock()

    def global_lock(self) -> FileLock:
        """Get the global database lock."""
        return self._global_lock

    def collection_lock(self, collection: str) -> FileLock:
        """Get a per-collection lock."""
        with self._lock_table:
            if collection not in self._collection_locks:
                safe = "".join(
                    c for c in collection
                    if c.isalnum() or c in "_-"
                )[:64]
                path = os.path.join(
                    self.data_dir, ".lock_" + safe
                )
                self._collection_locks[collection] = FileLock(
                    path
                )
            return self._collection_locks[collection]

    def release_all(self):
        """Release all held locks."""
        try:
            self._global_lock.release()
        except Exception:
            pass
        with self._lock_table:
            for lock in self._collection_locks.values():
                try:
                    lock.release()
                except Exception:
                    pass
