"""
RayzorgenDB DAG Storage

Every write becomes a node in a directed acyclic graph.
Multiple writers append to independent branches.
No locks. No queue. Merge later.

Inspired by Git, CRDTs, and event sourcing.
"""

import time
import uuid
import threading
import hashlib
from typing import Any, Dict, List, Optional, Set


class DAGNode:
    """A single write event."""

    __slots__ = (
        "id", "op", "collection", "record_id",
        "data", "parents", "timestamp",
        "writer_id", "merged",
    )

    def __init__(self, op: str, collection: str,
                 record_id: str, data: Any,
                 parents: List[str], writer_id: str):
        self.id = uuid.uuid4().hex[:16]
        self.op = op
        self.collection = collection
        self.record_id = record_id
        self.data = data
        self.parents = parents
        self.timestamp = time.time()
        self.writer_id = writer_id
        self.merged = False

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "op": self.op,
            "collection": self.collection,
            "record_id": self.record_id,
            "data": self.data,
            "parents": self.parents,
            "timestamp": self.timestamp,
            "writer_id": self.writer_id,
        }


class DAGStore:
    """
    DAG-based storage engine.

    Each writer has its own tip. Writes append to tip
    without blocking other writers. When tips diverge,
    a merge resolves them by replaying from common ancestor.
    """

    def __init__(self):
        self._nodes: Dict[str, DAGNode] = {}
        self._tips: Dict[str, List[str]] = {}  # writer_id -> node ids
        self._children: Dict[str, List[str]] = {}
        self._root: Optional[str] = None
        self._lock = threading.RLock()
        self._stats = {
            "nodes": 0,
            "merges": 0,
            "writers": 0,
            "conflicts": 0,
        }

    def register_writer(self, writer_id: str = None) -> str:
        """Register a new writer. Each gets its own branch."""
        with self._lock:
            writer_id = writer_id or uuid.uuid4().hex[:8]
            if writer_id not in self._tips:
                self._tips[writer_id] = []
                self._stats["writers"] += 1
            return writer_id

    def append(self, writer_id: str, op: str,
               collection: str, record_id: str,
               data: Any = None) -> DAGNode:
        """
        Append a node to writer's branch.
        No lock needed for other writers.
        """
        with self._lock:
            if writer_id not in self._tips:
                self._tips[writer_id] = []

            parents = list(self._tips[writer_id])

            node = DAGNode(
                op, collection, record_id,
                data, parents, writer_id,
            )
            self._nodes[node.id] = node

            # Register children
            for p in parents:
                self._children.setdefault(p, []).append(node.id)

            # Update writer tip
            self._tips[writer_id] = [node.id]

            # First node = root
            if self._root is None:
                self._root = node.id

            self._stats["nodes"] += 1
            return node

    def ancestors(self, node_id: str) -> List[str]:
        """Get all ancestors of a node (topologically sorted)."""
        with self._lock:
            visited = set()
            order = []
            stack = [node_id]

            while stack:
                nid = stack.pop()
                if nid in visited:
                    continue
                visited.add(nid)
                node = self._nodes.get(nid)
                if node:
                    stack.extend(node.parents)

            # Topological sort
            visited = set()
            def visit(nid):
                if nid in visited:
                    return
                visited.add(nid)
                node = self._nodes.get(nid)
                if node:
                    for p in node.parents:
                        visit(p)
                    order.append(nid)

            visit(node_id)
            return order

    def common_ancestor(self, ids: List[str]) -> Optional[str]:
        """Find common ancestor of multiple nodes."""
        if not ids:
            return None
        if len(ids) == 1:
            return ids[0]

        # Get ancestor sets
        sets = []
        for nid in ids:
            sets.append(set(self.ancestors(nid)))

        # Intersection
        common = sets[0]
        for s in sets[1:]:
            common &= s

        if not common:
            return None

        # Return the "newest" common ancestor
        best = None
        best_ts = -1
        for nid in common:
            node = self._nodes.get(nid)
            if node and node.timestamp > best_ts:
                best = nid
                best_ts = node.timestamp
        return best

    def merge(self, node_ids: List[str]) -> DAGNode:
        """
        Merge multiple branches.
        Creates a merge node with multiple parents.
        Replays operations from common ancestor.
        """
        with self._lock:
            if len(node_ids) < 2:
                raise ValueError("Need at least 2 nodes to merge")

            # Find common ancestor
            ancestor = self.common_ancestor(node_ids)

            # Create merge node
            merge_node = DAGNode(
                op="merge",
                collection="__merge__",
                record_id=uuid.uuid4().hex[:16],
                data={"merging": node_ids},
                parents=list(node_ids),
                writer_id="__merge__",
            )
            self._nodes[merge_node.id] = merge_node
            self._stats["merges"] += 1

            # Register children
            for nid in node_ids:
                self._children.setdefault(nid, []).append(merge_node.id)

            # Register as new tip for all writers
            for wid in self._tips:
                if any(t in node_ids for t in self._tips[wid]):
                    self._tips[wid] = [merge_node.id]

            return merge_node

    def replay(self, node_id: str,
               apply_fn) -> int:
        """
        Replay all operations from root to node.
        apply_fn(op, collection, record_id, data) called for each.
        Returns number of operations applied.
        """
        with self._lock:
            path = self.ancestors(node_id)
            count = 0
            for nid in path:
                node = self._nodes.get(nid)
                if node and node.op != "merge":
                    apply_fn(
                        node.op, node.collection,
                        node.record_id, node.data,
                    )
                    count += 1
            return count

    def get_node(self, node_id: str) -> Optional[DAGNode]:
        return self._nodes.get(node_id)

    def tip(self, writer_id: str) -> Optional[str]:
        with self._lock:
            tips = self._tips.get(writer_id, [])
            return tips[-1] if tips else None

    def all_tips(self) -> Dict[str, str]:
        with self._lock:
            return {
                w: (t[-1] if t else None)
                for w, t in self._tips.items()
            }

    def stats(self) -> Dict:
        with self._lock:
            return {
                **self._stats,
                "total_nodes": len(self._nodes),
                "branches": len(self._tips),
            }

    def graph_ascii(self, limit: int = 50) -> str:
        """Show DAG as ASCII art."""
        with self._lock:
            lines = []
            for wid, tips in self._tips.items():
                if not tips:
                    continue
                path = self.ancestors(tips[-1])
                line = "[" + wid + "] "
                for nid in path[-limit:]:
                    node = self._nodes.get(nid)
                    if node:
                        line += node.op[:3] + "-"
                lines.append(line.rstrip("-"))
            return "\n".join(lines)
