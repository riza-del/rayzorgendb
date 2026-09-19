"""
RayzorgenDB Change Data Capture

Real-time stream of changes.
Listeners get notified on insert/update/delete.

Usage:
    cdc = CDCStream()
    cdc.on_change(lambda event: print(event))
    cdc.emit("insert", "users", "id1", {"nama": "Budi"})
"""

import time
import threading
import uuid
from collections import deque
from typing import Any, Callable, Dict, List


class CDCEvent:
    __slots__ = (
        "id", "op", "collection", "record_id",
        "data", "old_data", "at", "tx_id",
    )

    def __init__(self, op, collection, record_id,
                 data=None, old_data=None, tx_id=None):
        self.id = uuid.uuid4().hex[:12]
        self.op = op
        self.collection = collection
        self.record_id = record_id
        self.data = data
        self.old_data = old_data
        self.at = time.time()
        self.tx_id = tx_id

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "op": self.op,
            "collection": self.collection,
            "record_id": self.record_id,
            "data": self.data,
            "old_data": self.old_data,
            "at": self.at,
            "tx_id": self.tx_id,
        }


class CDCStream:
    """
    Change Data Capture stream.

    Features:
    - Listeners (callback)
    - Ring buffer history
    - Filter by collection/op
    - Replay changes
    """

    def __init__(self, max_buffer: int = 10000):
        self.max_buffer = max_buffer
        self._buffer: deque = deque(maxlen=max_buffer)
        self._listeners: List[Dict] = []
        self._lock = threading.RLock()
        self._stats = {
            "total_events": 0,
            "by_op": {},
        }

    def emit(self, op: str, collection: str,
             record_id: str, data: Dict = None,
             old_data: Dict = None,
             tx_id: str = None):
        """Emit a change event."""
        event = CDCEvent(
            op, collection, record_id,
            data, old_data, tx_id,
        )
        with self._lock:
            self._buffer.append(event)
            self._stats["total_events"] += 1
            self._stats["by_op"][op] = (
                self._stats["by_op"].get(op, 0) + 1
            )

            # Notify listeners
            for listener in list(self._listeners):
                try:
                    # Filter
                    if listener["collection"] and                             listener["collection"] != collection:
                        continue
                    if listener["op"] and                             listener["op"] != op:
                        continue
                    listener["callback"](event)
                except Exception:
                    pass

    def on_change(self, callback: Callable,
                  collection: str = None,
                  op: str = None) -> str:
        """
        Register a listener.
        Returns listener ID.
        """
        listener_id = uuid.uuid4().hex[:8]
        with self._lock:
            self._listeners.append({
                "id": listener_id,
                "callback": callback,
                "collection": collection,
                "op": op,
            })
        return listener_id

    def off(self, listener_id: str) -> bool:
        with self._lock:
            for i, l in enumerate(self._listeners):
                if l["id"] == listener_id:
                    self._listeners.pop(i)
                    return True
        return False

    def recent(self, n: int = 20) -> List[Dict]:
        with self._lock:
            return [e.to_dict() for e in list(self._buffer)[-n:]]

    def since(self, timestamp: float) -> List[Dict]:
        """Get all events since timestamp."""
        with self._lock:
            return [
                e.to_dict() for e in self._buffer
                if e.at >= timestamp
            ]

    def filter(self, op: str = None,
               collection: str = None,
               limit: int = None) -> List[Dict]:
        with self._lock:
            events = []
            for e in self._buffer:
                if op and e.op != op:
                    continue
                if collection and e.collection != collection:
                    continue
                events.append(e.to_dict())
                if limit and len(events) >= limit:
                    break
            return events

    def stats(self) -> Dict:
        with self._lock:
            return {
                **self._stats,
                "buffer_size": len(self._buffer),
                "max_buffer": self.max_buffer,
                "listeners": len(self._listeners),
            }

    def clear(self):
        with self._lock:
            self._buffer.clear()
            self._stats = {
                "total_events": 0,
                "by_op": {},
            }


__all__ = ["CDCStream", "CDCEvent"]
