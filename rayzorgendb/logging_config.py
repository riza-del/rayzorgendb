"""
RayzorgenDB Structured Logging

Log every important operation. JSON lines format.
"""

import os
import sys
import json
import time
import threading
from typing import Any, Dict, Optional


LEVELS = {
    "DEBUG": 10,
    "INFO": 20,
    "WARNING": 30,
    "ERROR": 40,
    "CRITICAL": 50,
}


class Logger:
    """Structured logger with JSON output."""

    def __init__(self, name: str = "rayzorgendb",
                 level: str = "INFO",
                 output: str = None,
                 to_console: bool = True):
        self.name = name
        self.level = LEVELS.get(level.upper(), 20)
        self.output = output
        self.to_console = to_console
        self._lock = threading.RLock()
        self._file = None

        if output:
            os.makedirs(
                os.path.dirname(output) or ".",
                exist_ok=True,
            )
            self._file = open(output, "a")

    def _write(self, level: str, message: str,
               extra: Dict = None):
        if LEVELS.get(level, 0) < self.level:
            return

        entry = {
            "ts": round(time.time(), 3),
            "level": level,
            "name": self.name,
            "msg": message,
        }
        if extra:
            entry.update(extra)

        line = json.dumps(entry, default=str)

        with self._lock:
            if self._file:
                try:
                    self._file.write(line + "\n")
                    self._file.flush()
                except Exception:
                    pass
            if self.to_console:
                try:
                    sys.stderr.write(line + "\n")
                except Exception:
                    pass

    def debug(self, msg: str, **kwargs):
        self._write("DEBUG", msg, kwargs)

    def info(self, msg: str, **kwargs):
        self._write("INFO", msg, kwargs)

    def warning(self, msg: str, **kwargs):
        self._write("WARNING", msg, kwargs)

    def error(self, msg: str, **kwargs):
        self._write("ERROR", msg, kwargs)

    def critical(self, msg: str, **kwargs):
        self._write("CRITICAL", msg, kwargs)

    def close(self):
        with self._lock:
            if self._file:
                try:
                    self._file.close()
                except Exception:
                    pass
                self._file = None


# Global logger
_global = Logger(to_console=False)


def get_logger(name: str = None) -> Logger:
    """Get or create a logger."""
    if name is None:
        return _global
    return Logger(name=name, to_console=False)


def configure(level: str = "INFO",
              output: str = None,
              to_console: bool = True):
    """Configure global logger."""
    global _global
    _global = Logger(
        name="rayzorgendb",
        level=level,
        output=output,
        to_console=to_console,
    )
    return _global


__all__ = ["Logger", "get_logger", "configure", "LEVELS"]
