"""
RayzorgenDB Replication

Primary-Replica replication via socket.
Primary accepts writes, Replica receives WAL stream.

Usage:
    # Primary
    primary = Primary("./data", port=9999)
    primary.start()

    # Replica
    replica = Replica("./replica_data", "localhost", 9999)
    replica.connect()
"""

import os
import sys
import json
import time
import socket
import struct
import threading
import pickle
from typing import Any, Dict, List, Optional


MAGIC = b"RREP"
OP_INSERT = 1
OP_UPDATE = 2
OP_DELETE = 3
OP_SYNC_REQUEST = 4
OP_SYNC_RESPONSE = 5
OP_PING = 6
OP_PONG = 7


def pack_message(op: int, payload: Any) -> bytes:
    data = pickle.dumps(payload)
    return struct.pack(">B", op) + struct.pack(">I", len(data)) + data


def recv_message(sock: socket.socket) -> Optional[tuple]:
    header = recv_all(sock, 5)
    if not header:
        return None
    op = header[0]
    size = struct.unpack(">I", header[1:5])[0]
    if size > 100 * 1024 * 1024:
        return None
    data = recv_all(sock, size)
    if data is None:
        return None
    try:
        return op, pickle.loads(data)
    except Exception:
        return None


def recv_all(sock: socket.socket, n: int) -> Optional[bytes]:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


class Primary:
    """Primary server for replication."""

    def __init__(self, db, host: str = "0.0.0.0",
                 port: int = 9999):
        self.db = db
        self.host = host
        self.port = port
        self._server = None
        self._thread = None
        self._clients: List[socket.socket] = []
        self._lock = threading.RLock()
        self._running = False
        self._stats = {
            "clients_connected": 0,
            "operations_sent": 0,
        }
        self._setup_cdc()

    def _setup_cdc(self):
        """Hook into CDC to broadcast changes."""
        try:
            # Akses langsung cdc_stream di core
            core = self.db.core
            cdc = getattr(core, "cdc_stream", None)
            if cdc is not None:
                cdc.on_change(self._on_change)
            else:
                # Fallback ke facade
                cdc = self.db.cdc()
                cdc.on_change(self._on_change)
        except Exception as e:
            print("[replication] CDC hook error: " + str(e))

    def _on_change(self, event):
        """Broadcast to all replica clients."""
        with self._lock:
            clients = list(self._clients)
        for c in clients:
            try:
                self._send_event(c, event)
            except Exception:
                self._remove_client(c)

    def _send_event(self, sock: socket.socket, event):
        op_map = {
            "insert": OP_INSERT,
            "update": OP_UPDATE,
            "delete": OP_DELETE,
        }
        op = op_map.get(event.op, OP_INSERT)
        payload = {
            "collection": event.collection,
            "record_id": event.record_id,
            "data": event.data,
            "version": 1,
        }
        msg = pack_message(op, payload)
        sock.sendall(msg)
        with self._lock:
            self._stats["operations_sent"] += 1

    def start(self):
        """Start listening for replicas."""
        self._server = socket.socket(
            socket.AF_INET, socket.SOCK_STREAM
        )
        self._server.setsockopt(
            socket.SOL_SOCKET, socket.SO_REUSEADDR, 1
        )
        self._server.bind((self.host, self.port))
        self._server.listen(5)
        self._running = True

        self._thread = threading.Thread(
            target=self._accept_loop, daemon=True
        )
        self._thread.start()
        return self

    def _accept_loop(self):
        while self._running:
            try:
                client, addr = self._server.accept()
            except OSError:
                break
            with self._lock:
                self._clients.append(client)
                self._stats["clients_connected"] += 1
            # Handle in separate thread
            threading.Thread(
                target=self._handle_client,
                args=(client,),
                daemon=True,
            ).start()

    def _handle_client(self, sock: socket.socket):
        """Handle client messages (pings, etc)."""
        try:
            while self._running:
                msg = recv_message(sock)
                if msg is None:
                    break
                op, payload = msg
                if op == OP_PING:
                    sock.sendall(pack_message(OP_PONG, {}))
        except Exception:
            pass
        finally:
            self._remove_client(sock)

    def _remove_client(self, sock: socket.socket):
        with self._lock:
            if sock in self._clients:
                self._clients.remove(sock)
        try:
            sock.close()
        except Exception:
            pass

    def stop(self):
        self._running = False
        try:
            if self._server:
                self._server.close()
        except Exception:
            pass
        with self._lock:
            for c in self._clients:
                try:
                    c.close()
                except Exception:
                    pass
            self._clients.clear()

    def stats(self) -> Dict:
        with self._lock:
            return {
                **self._stats,
                "running": self._running,
                "host": self.host,
                "port": self.port,
                "active_clients": len(self._clients),
            }


class Replica:
    """Replica that receives changes from primary."""

    def __init__(self, db, host: str = "localhost",
                 port: int = 9999):
        self.db = db
        self.host = host
        self.port = port
        self._sock = None
        self._thread = None
        self._running = False
        self._lock = threading.RLock()
        self._stats = {
            "operations_received": 0,
            "errors": 0,
        }

    def connect(self) -> bool:
        """Connect to primary."""
        try:
            self._sock = socket.socket(
                socket.AF_INET, socket.SOCK_STREAM
            )
            self._sock.connect((self.host, self.port))
            self._running = True
            self._thread = threading.Thread(
                target=self._receive_loop, daemon=True
            )
            self._thread.start()
            return True
        except (OSError, socket.error):
            self._sock = None
            return False

    def _receive_loop(self):
        while self._running:
            msg = recv_message(self._sock)
            if msg is None:
                self._running = False
                break
            op, payload = msg
            try:
                self._apply(op, payload)
                with self._lock:
                    self._stats["operations_received"] += 1
            except Exception:
                with self._lock:
                    self._stats["errors"] += 1

    def _apply(self, op: int, payload: Dict):
        """Apply change to local database."""
        collection = payload.get("collection")
        record_id = payload.get("record_id")
        data = payload.get("data", {})

        if op == OP_INSERT:
            # Insert with same ID
            rec = self.db.collection(collection).insert(data)
        elif op == OP_UPDATE:
            self.db.collection(collection).update(
                record_id, data
            )
        elif op == OP_DELETE:
            self.db.collection(collection).delete(record_id)

    def stop(self):
        self._running = False
        try:
            if self._sock:
                self._sock.close()
        except Exception:
            pass

    def stats(self) -> Dict:
        with self._lock:
            return {
                **self._stats,
                "connected": self._running,
                "host": self.host,
                "port": self.port,
            }


class ReplicationManager:
    """Facade for replication."""

    def __init__(self, db, mode: str = "primary",
                 host: str = "localhost", port: int = 9999):
        self.db = db
        self.mode = mode
        self.host = host
        self.port = port
        self.node = None

    def start_primary(self, host: str = "0.0.0.0",
                      port: int = 9999):
        self.mode = "primary"
        self.node = Primary(self.db, host, port).start()
        return self.node

    def start_replica(self, host: str = "localhost",
                      port: int = 9999) -> bool:
        self.mode = "replica"
        self.node = Replica(self.db, host, port)
        return self.node.connect()

    def stop(self):
        if self.node:
            self.node.stop()

    def stats(self) -> Dict:
        if self.node:
            return {
                "mode": self.mode,
                **self.node.stats(),
            }
        return {"mode": self.mode, "node": None}


__all__ = ["Primary", "Replica", "ReplicationManager"]
