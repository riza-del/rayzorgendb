"""
RayzorgenDB HNSW Vector Index

Hierarchical Navigable Small World graph for fast
approximate nearest neighbor search.

How it works:
- Multi-layer graph. Layer 0 has all nodes.
- Upper layers are sparse shortcuts.
- Search descends from top layer.
- Each node has M neighbors per layer.
- Insert uses random level assignment.

Complexity:
- Search: O(log n) instead of O(n)
- Insert: O(log n)
- Memory: O(n * M)

Usage:
    index = HNSWIndex(dim=128, m=16)
    index.insert("id1", [0.1, 0.2, ...])
    results = index.search([0.1, 0.2, ...], k=5)
    # [("id1", 0.02), ("id2", 0.15), ...]
"""

import math
import heapq
import random
import threading
from typing import Any, Dict, List, Optional, Tuple


# Try to use native Rust for speed
try:
    from rayzorgendb.native_ffi import (
        cosine_distance as _native_cos_dist,
    )
    _USE_NATIVE = True
except ImportError:
    _USE_NATIVE = False


def cosine_distance(a: List[float], b: List[float]) -> float:
    """1 - cosine similarity (0 = identical, 2 = opposite)."""
    if _USE_NATIVE:
        return _native_cos_dist(a, b)
    if not a or not b or len(a) != len(b):
        return 1.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0 or nb == 0:
        return 1.0
    sim = dot / (math.sqrt(na) * math.sqrt(nb))
    if sim > 1.0:
        sim = 1.0
    elif sim < -1.0:
        sim = -1.0
    return 1.0 - sim


def euclidean_distance(a: List[float], b: List[float]) -> float:
    """Euclidean distance."""
    if not a or not b or len(a) != len(b):
        return float("inf")
    total = 0.0
    for x, y in zip(a, b):
        d = x - y
        total += d * d
    return math.sqrt(total)


class HNSWNode:
    """A single node in the HNSW graph."""

    __slots__ = ("id", "vector", "level", "neighbors")

    def __init__(self, node_id: str, vector: List[float],
                 level: int):
        self.id = node_id
        self.vector = vector
        self.level = level
        # neighbors[layer] = list of node_ids
        self.neighbors: List[List[str]] = [
            [] for _ in range(level + 1)
        ]


class HNSWIndex:
    """
    Hierarchical Navigable Small World index.

    Params:
        dim: vector dimension
        m: max neighbors per node per layer (default 16)
        ef_construction: search depth during insert (default 200)
        ef_search: search depth during query (default 50)
        metric: "cosine" or "euclidean"
        seed: random seed
    """

    def __init__(self, dim: int, m: int = 16,
                 ef_construction: int = 200,
                 ef_search: int = 50,
                 metric: str = "cosine",
                 seed: int = 42):
        self.dim = dim
        self.m = m
        self.m_max = m
        self.m_max0 = m * 2  # Layer 0 allows more neighbors
        self.ef_construction = ef_construction
        self.ef_search = ef_search
        self.metric = metric
        self._rng = random.Random(seed)
        self._lock = threading.RLock()

        self._nodes: Dict[str, HNSWNode] = {}
        self._entry_point: Optional[str] = None
        self._max_level = -1
        self._ml = 1.0 / math.log(m)  # Level generation factor

        if metric == "cosine":
            self._distance = cosine_distance
        else:
            self._distance = euclidean_distance

    # --------------------------------------------------------
    # Level assignment
    # --------------------------------------------------------

    def _random_level(self) -> int:
        """Generate random level with exponential decay."""
        r = self._rng.random()
        if r == 0:
            r = 1e-10
        return int(-math.log(r) * self._ml)

    # --------------------------------------------------------
    # Insert
    # --------------------------------------------------------

    def insert(self, node_id: str, vector: List[float]):
        """Insert a vector into the index."""
        if len(vector) != self.dim:
            raise ValueError(
                "Vector dimension mismatch: expected " +
                str(self.dim) + ", got " + str(len(vector))
            )
        with self._lock:
            if node_id in self._nodes:
                self._delete_node(node_id)

            level = self._random_level()
            node = HNSWNode(node_id, list(vector), level)
            self._nodes[node_id] = node

            # First node
            if self._entry_point is None:
                self._entry_point = node_id
                self._max_level = level
                return

            curr = self._entry_point
            curr_dist = self._distance(vector, self._nodes[curr].vector)

            # Descend from top to node.level + 1
            for layer in range(self._max_level, level, -1):
                changed = True
                while changed:
                    changed = False
                    for nbr_id in self._nodes[curr].neighbors[layer]                             if layer < len(self._nodes[curr].neighbors) else []:
                        nbr = self._nodes.get(nbr_id)
                        if nbr is None:
                            continue
                        d = self._distance(vector, nbr.vector)
                        if d < curr_dist:
                            curr = nbr_id
                            curr_dist = d
                            changed = True

            # Insert at layers from min(level, max_level) down to 0
            start_layer = min(level, self._max_level)
            ep = [curr]
            for layer in range(start_layer, -1, -1):
                candidates = self._search_layer(
                    vector, ep, self.ef_construction, layer
                )
                # Take M nearest
                max_m = self.m_max0 if layer == 0 else self.m_max
                neighbors = self._select_neighbors(
                    vector, candidates, max_m
                )
                # Connect
                for nbr_id, _ in neighbors:
                    self._add_edge(node_id, nbr_id, layer)
                # Update entry for next iteration
                ep = [n[0] for n in neighbors] or ep
                if ep:
                    # Keep closest as entry
                    ep.sort(key=lambda x: self._distance(
                        vector, self._nodes[x].vector
                    ))
                    ep = [ep[0]]

            # Update entry point if new node has higher level
            if level > self._max_level:
                self._max_level = level
                self._entry_point = node_id

    def _select_neighbors(self, query_vector: List[float],
                          candidates: List[Tuple[str, float]],
                          m: int) -> List[Tuple[str, float]]:
        """
        Pick m nearest candidates.
        candidates: [(node_id, distance), ...]
        Returns: [(node_id, distance), ...] sorted, max m items.
        """
        scored = []
        for node_id, _ in candidates:
            node = self._nodes.get(node_id)
            if node is None:
                continue
            d = self._distance(query_vector, node.vector)
            scored.append((d, node_id))
        scored.sort()
        return [(nid, d) for d, nid in scored[:m]]

    def _add_edge(self, a_id: str, b_id: str, layer: int):
        """Add bidirectional edge."""
        a = self._nodes[a_id]
        b = self._nodes[b_id]
        while len(a.neighbors) <= layer:
            a.neighbors.append([])
        while len(b.neighbors) <= layer:
            b.neighbors.append([])
        if b_id not in a.neighbors[layer]:
            a.neighbors[layer].append(b_id)
        if a_id not in b.neighbors[layer]:
            b.neighbors[layer].append(a_id)

        # Prune if too many neighbors
        max_m = self.m_max0 if layer == 0 else self.m_max
        if len(b.neighbors[layer]) > max_m:
            self._prune(b, layer, max_m)

    def _prune(self, node: HNSWNode, layer: int, max_m: int):
        """Keep only the M closest neighbors."""
        neighbors = node.neighbors[layer]
        if len(neighbors) <= max_m:
            return
        scored = []
        for nbr_id in neighbors:
            nbr = self._nodes.get(nbr_id)
            if nbr is not None:
                d = self._distance(node.vector, nbr.vector)
                scored.append((d, nbr_id))
        scored.sort()
        node.neighbors[layer] = [
            n[1] for n in scored[:max_m]
        ]

    def _delete_node(self, node_id: str):
        node = self._nodes.get(node_id)
        if node is None:
            return
        # Remove from neighbors
        for layer_neighbors in node.neighbors:
            for nbr_id in layer_neighbors:
                nbr = self._nodes.get(nbr_id)
                if nbr:
                    for l in range(len(nbr.neighbors)):
                        try:
                            nbr.neighbors[l].remove(node_id)
                        except (ValueError, IndexError):
                            pass
        del self._nodes[node_id]
        # Update entry point if needed
        if self._entry_point == node_id:
            if self._nodes:
                self._entry_point = next(iter(self._nodes))
                self._max_level = self._nodes[
                    self._entry_point
                ].level
            else:
                self._entry_point = None
                self._max_level = -1

    # --------------------------------------------------------
    # Search
    # --------------------------------------------------------

    def _search_layer(self, query: List[float],
                      entry_points: List[str],
                      ef: int, layer: int) -> List[Tuple[str, float]]:
        """Greedy search within a layer."""
        visited = set(entry_points)
        candidates = []  # min-heap by distance
        results = []     # max-heap by distance (store negative)

        for ep in entry_points:
            n = self._nodes.get(ep)
            if n is None:
                continue
            d = self._distance(query, n.vector)
            heapq.heappush(candidates, (d, ep))
            heapq.heappush(results, (-d, ep))

        while candidates:
            d, curr_id = heapq.heappop(candidates)
            if results and -results[0][0] < d:
                break
            if len(results) >= ef and -results[0][0] < d:
                break

            curr = self._nodes.get(curr_id)
            if curr is None or layer >= len(curr.neighbors):
                continue

            for nbr_id in curr.neighbors[layer]:
                if nbr_id in visited:
                    continue
                visited.add(nbr_id)
                nbr = self._nodes.get(nbr_id)
                if nbr is None:
                    continue
                nd = self._distance(query, nbr.vector)
                if len(results) < ef or nd < -results[0][0]:
                    heapq.heappush(candidates, (nd, nbr_id))
                    heapq.heappush(results, (-nd, nbr_id))
                    if len(results) > ef:
                        heapq.heappop(results)

        out = [(-d, nid) for d, nid in results]
        out.sort()
        return [(nid, d) for d, nid in out]

    def search(self, query: List[float],
               k: int = 5) -> List[Tuple[str, float]]:
        """
        Find k nearest neighbors.
        Returns [(node_id, distance), ...] sorted by distance.
        """
        if len(query) != self.dim:
            raise ValueError(
                "Query dimension mismatch: expected " +
                str(self.dim) + ", got " + str(len(query))
            )
        with self._lock:
            if self._entry_point is None:
                return []

            curr = self._entry_point
            curr_dist = self._distance(
                query, self._nodes[curr].vector
            )

            # Descend from top layer to layer 1
            for layer in range(self._max_level, 0, -1):
                changed = True
                while changed:
                    changed = False
                    node = self._nodes.get(curr)
                    if node is None or layer >= len(node.neighbors):
                        break
                    for nbr_id in node.neighbors[layer]:
                        nbr = self._nodes.get(nbr_id)
                        if nbr is None:
                            continue
                        d = self._distance(query, nbr.vector)
                        if d < curr_dist:
                            curr = nbr_id
                            curr_dist = d
                            changed = True

            # Layer 0: full search
            ef = max(self.ef_search, k)
            candidates = self._search_layer(query, [curr], ef, 0)
            return candidates[:k]

    # --------------------------------------------------------
    # Search batch
    # --------------------------------------------------------

    def search_batch(self, queries: List[List[float]],
                     k: int = 5) -> List[List[Tuple[str, float]]]:
        return [self.search(q, k) for q in queries]

    # --------------------------------------------------------
    # Utilities
    # --------------------------------------------------------

    def delete(self, node_id: str) -> bool:
        with self._lock:
            if node_id not in self._nodes:
                return False
            self._delete_node(node_id)
            return True

    def get(self, node_id: str) -> Optional[HNSWNode]:
        return self._nodes.get(node_id)

    def size(self) -> int:
        return len(self._nodes)

    def stats(self) -> Dict:
        with self._lock:
            total_edges = 0
            for node in self._nodes.values():
                for layer_neighbors in node.neighbors:
                    total_edges += len(layer_neighbors)
            return {
                "size": len(self._nodes),
                "dim": self.dim,
                "m": self.m,
                "max_level": self._max_level,
                "entry_point": self._entry_point,
                "total_edges": total_edges,
                "avg_edges_per_node": round(
                    total_edges / max(len(self._nodes), 1), 2
                ),
            }

    def clear(self):
        with self._lock:
            self._nodes.clear()
            self._entry_point = None
            self._max_level = -1


__all__ = ["HNSWIndex", "HNSWNode", "cosine_distance",
           "euclidean_distance"]
