"""
RayzorgenDB Smart Layer

Optional, unified, easy-to-use interface.
Provides simple verbs and advanced helpers
without exposing internal module structure.

Usage:
    from rayzorgendb import RayzorgenDB

    db = RayzorgenDB()
    db.add("users", {"name": "Budi"})
    db.find("users")
    db.score("users", [...])
"""

import os
import time
import uuid
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple


# ============================================================
# Scored Query (multi-condition)
# ============================================================

class Condition:
    """A single weighted condition."""

    def __init__(self, field: str, op: str,
                 value: Any, weight: float = 1.0):
        self.field = field
        self.op = op
        self.value = value
        self.weight = weight

    def score(self, record: Dict) -> float:
        v = self._get(record, self.field)
        if v is None:
            return 0.0
        try:
            if self.op == "eq":
                return 1.0 if v == self.value else 0.0
            if self.op == "ne":
                return 1.0 if v != self.value else 0.0
            if self.op == "gt":
                return 1.0 if v > self.value else 0.0
            if self.op == "lt":
                return 1.0 if v < self.value else 0.0
            if self.op == "gte":
                return 1.0 if v >= self.value else 0.0
            if self.op == "lte":
                return 1.0 if v <= self.value else 0.0
            if self.op == "contains":
                return 1.0 if str(self.value) in str(v) else 0.0
            if self.op == "icontains":
                return 1.0 if str(self.value).lower() \
                    in str(v).lower() else 0.0
            if self.op == "between":
                lo, hi = self.value
                if lo <= v <= hi:
                    mid = (lo + hi) / 2
                    dist = abs(v - mid)
                    rng = (hi - lo) / 2
                    return 1.0 - (dist / rng) * 0.5 \
                        if rng > 0 else 1.0
                return 0.0
            if self.op == "near":
                if not isinstance(v, (int, float)):
                    return 0.0
                dist = abs(v - self.value)
                return 1.0 / (1.0 + dist)
        except (TypeError, AttributeError):
            return 0.0
        return 0.0

    @staticmethod
    def _get(record: Dict, path: str) -> Any:
        cur = record
        for p in path.split("."):
            if isinstance(cur, dict) and p in cur:
                cur = cur[p]
            else:
                return None
        return cur


class ScoredResult:
    """Scored query result set."""

    def __init__(self, rows: List[Dict]):
        self._rows = rows

    def all(self, limit: int = None,
            threshold: float = 0.0) -> List[Dict]:
        rows = [r for r in self._rows
                if r["score"] >= threshold]
        if limit:
            rows = rows[:limit]
        return rows

    def first(self, threshold: float = 0.5) -> Optional[Dict]:
        rows = self.all(limit=1, threshold=threshold)
        return rows[0] if rows else None


# ============================================================
# Graph (multi-writer DAG)
# ============================================================

class _DAGNode:
    __slots__ = (
        "id", "op", "collection", "record_id",
        "data", "parents", "timestamp", "writer",
    )

    def __init__(self, op, collection, record_id,
                 data, parents, writer):
        self.id = uuid.uuid4().hex[:16]
        self.op = op
        self.collection = collection
        self.record_id = record_id
        self.data = data
        self.parents = parents
        self.timestamp = time.time()
        self.writer = writer

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "op": self.op,
            "collection": self.collection,
            "record_id": self.record_id,
            "data": self.data,
            "parents": self.parents,
            "timestamp": self.timestamp,
            "writer": self.writer,
        }


class _Graph:
    """Internal multi-writer DAG."""

    def __init__(self):
        self._nodes: Dict[str, _DAGNode] = {}
        self._tips: Dict[str, List[str]] = {}
        self._children: Dict[str, List[str]] = {}
        self._root: Optional[str] = None
        self._lock = threading.RLock()

    def open(self, name: str = None) -> str:
        with self._lock:
            name = name or uuid.uuid4().hex[:8]
            if name not in self._tips:
                self._tips[name] = []
            return name

    def write(self, branch: str, op: str,
              collection: str, record_id: str,
              data: Any = None) -> _DAGNode:
        with self._lock:
            if branch not in self._tips:
                self._tips[branch] = []

            node = _DAGNode(
                op, collection, record_id,
                data, list(self._tips[branch]), branch,
            )
            self._nodes[node.id] = node

            for p in node.parents:
                self._children.setdefault(p, []).append(node.id)

            self._tips[branch] = [node.id]
            if self._root is None:
                self._root = node.id
            return node

    def ancestors(self, node_id: str) -> List[str]:
        visited = set()
        order = []

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

    def merge(self, ids: List[str]) -> _DAGNode:
        with self._lock:
            if len(ids) < 2:
                raise ValueError("Need 2+ nodes")

            merge = _DAGNode(
                "merge", "__merge__",
                uuid.uuid4().hex[:16],
                {"merging": ids},
                list(ids), "__merge__",
            )
            self._nodes[merge.id] = merge

            for wid in self._tips:
                if any(t in ids for t in self._tips[wid]):
                    self._tips[wid] = [merge.id]
            return merge

    def replay(self, node_id: str, apply_fn) -> int:
        count = 0
        for nid in self.ancestors(node_id):
            node = self._nodes.get(nid)
            if node and node.op != "merge":
                apply_fn(node.op, node.collection,
                         node.record_id, node.data)
                count += 1
        return count

    def tip(self, branch: str) -> Optional[str]:
        tips = self._tips.get(branch, [])
        return tips[-1] if tips else None

    def branches(self) -> List[str]:
        return list(self._tips.keys())

    def stats(self) -> Dict:
        return {
            "nodes": len(self._nodes),
            "branches": len(self._tips),
        }


# ============================================================
# Reactive (auto fields)
# ============================================================

class _ReactiveLink:
    def __init__(self, source_box, source_field,
                 target_box, target_field,
                 compute, match_on):
        self.source_box = source_box
        self.source_field = source_field
        self.target_box = target_box
        self.target_field = target_field
        self.compute = compute
        self.match_on = match_on


class _Reactive:
    def __init__(self, db):
        self._db = db
        self._links: List[_ReactiveLink] = []
        self._lock = threading.RLock()

    def link(self, source: Tuple[str, str],
             target: Tuple[str, str],
             compute: Callable,
             match_on: str = "id") -> _ReactiveLink:
        link = _ReactiveLink(
            source[0], source[1],
            target[0], target[1],
            compute, match_on,
        )
        with self._lock:
            self._links.append(link)
        return link

    def values_for(self, box: str,
                   record: Dict) -> Dict:
        result = {}
        with self._lock:
            links = [l for l in self._links
                     if l.target_box == box]
        for link in links:
            try:
                src = self._db.collection(link.source_box)
                match_val = record.get("id")
                recs = [
                    s.to_dict() for s in src.all()
                    if s.data.get(link.source_field) == match_val
                ]
                result[link.target_field] = link.compute(recs)
            except Exception:
                result[link.target_field] = None
        return result


# ============================================================
# Smart Layer - the unified interface
# ============================================================

class Smart:
    """
    Smart layer attached to RayzorgenDB.

    Accessed via db.<method>:

        db.add(box, data)
        db.find(box)
        db.change(box, id, data)
        db.remove(box, id)
        db.score(box, conditions)
        db.link(source, target, compute)
    """

    def __init__(self, db):
        self._db = db
        self.graph = _Graph()
        self.reactive = _Reactive(db)
        # Self-aliases for convenience
        self.brain = self
        self.scored = self
        self._started_at = time.time()
        self._log: List[Dict] = []
        self._lock = threading.RLock()

    def _log_action(self, action: str, box: str):
        with self._lock:
            self._log.append({
                "action": action,
                "box": box,
                "at": time.time(),
            })
            if len(self._log) > 1000:
                self._log = self._log[-500:]

    # --------------------------------------------------------
    # Simple verbs
    # --------------------------------------------------------

    def add(self, box: str, data: Dict) -> Dict:
        """Add one item to a box."""
        self._log_action("add", box)
        try:
            rec = self._db.collection(box).insert(data)
            return {"ok": True, "id": rec.id}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def add_many(self, box: str,
                 items: List[Dict]) -> Dict:
        """Add many items at once."""
        self._log_action("add_many", box)
        try:
            self._db.begin_batch()
            for item in items:
                self._db.collection(box).insert(item)
            self._db.end_batch()
            return {"ok": True, "added": len(items)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def find(self, box: str, field: str = None,
             value: Any = None) -> List[Dict]:
        """Find items in a box. Optional filter."""
        self._log_action("find", box)
        try:
            coll = self._db.collection(box)
            if field is None:
                records = coll.all()
            else:
                records = coll.query() \
                    .where(field, "eq", value).all()

            result = []
            for r in records:
                d = r.to_dict() if hasattr(r, "to_dict") else r
                try:
                    extra = self.reactive.values_for(box, d)
                    if extra:
                        d.setdefault("data", {}).update(extra)
                except Exception:
                    pass
                result.append(d)
            return result
        except Exception:
            return []

    def find_like(self, box: str, text: str,
                  limit: int = 20) -> List[Dict]:
        """Search anywhere in the box."""
        self._log_action("find_like", box)
        try:
            records = self._db.collection(box).search(text)
            return [
                r.to_dict() if hasattr(r, "to_dict") else r
                for r in records[:limit]
            ]
        except Exception:
            return []

    def change(self, box: str, record_id: str,
               new_data: Dict) -> Dict:
        """Change fields on a record."""
        self._log_action("change", box)
        try:
            rec = self._db.collection(box).update(
                record_id, new_data
            )
            if rec is None:
                return {"ok": False, "error": "not found"}
            return {"ok": True, "id": record_id}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def remove(self, box: str, record_id: str) -> Dict:
        """Remove one record."""
        self._log_action("remove", box)
        try:
            ok = self._db.collection(box).delete(record_id)
            return {"ok": ok}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def count(self, box: str) -> int:
        try:
            return self._db.collection(box).count()
        except Exception:
            return 0

    def boxes(self) -> List[str]:
        try:
            return self._db.collections()
        except Exception:
            return []

    def empty(self, box: str) -> bool:
        try:
            self._db.drop_collection(box)
            return True
        except Exception:
            return False

    # --------------------------------------------------------
    # Advanced
    # --------------------------------------------------------

    def score(self, box: str,
              conditions: List[Condition]) -> ScoredResult:
        """Ranked query with weighted conditions."""
        try:
            records = self._db.collection(box).all()
            records = [
                r.to_dict() if hasattr(r, "to_dict") else r
                for r in records
            ]
        except Exception:
            records = []

        rows = []
        for rec in records:
            data = rec.get("data", rec)
            total_w = 0.0
            weighted = 0.0
            for cond in conditions:
                s = cond.score(data)
                weighted += s * cond.weight
                total_w += cond.weight
            score = weighted / total_w if total_w > 0 else 0.0
            rows.append({"record": rec, "score": round(score, 4)})

        rows.sort(key=lambda r: r["score"], reverse=True)
        return ScoredResult(rows)

    def link(self, source: Tuple[str, str],
             target: Tuple[str, str],
             compute: Callable,
             match_on: str = "id") -> _ReactiveLink:
        """Create reactive link between two boxes."""
        return self.reactive.link(
            source, target, compute, match_on
        )

    def branch(self, name: str = None) -> str:
        """Open a new writer branch."""
        return self.graph.open(name)

    def write_branch(self, branch: str, op: str,
                     box: str, record_id: str,
                     data: Any = None) -> _DAGNode:
        """Write to a specific branch."""
        return self.graph.write(
            branch, op, box, record_id, data
        )

    def merge_branches(self, node_ids: List[str]) -> _DAGNode:
        """Merge multiple branches."""
        return self.graph.merge(node_ids)

    def graph_stats(self) -> Dict:
        return self.graph.stats()

    # --------------------------------------------------------
    # Self-awareness
    # --------------------------------------------------------

    def tell_me_about_yourself(self) -> str:
        boxes = self.boxes()
        total = sum(self.count(b) for b in boxes)
        uptime = int(time.time() - self._started_at)

        lines = ["I am RayzorgenDB.", ""]
        lines.append("I hold " + str(total) + " items "
                     "across " + str(len(boxes)) + " boxes.")
        if boxes:
            lines.append("")
            lines.append("My boxes:")
            for b in boxes:
                lines.append("  - " + b + " (" +
                             str(self.count(b)) + " items)")
        lines.append("")
        lines.append("Awake for " + str(uptime) + " seconds.")
        return "\n".join(lines)

    def check_health(self) -> Dict:
        result = {"ok": True, "problems": [], "boxes": {}}

        folder = getattr(self._db.config, "DATA_DIR", None)
        if folder and not os.path.exists(folder):
            result["problems"].append("Data folder missing")
            result["ok"] = False

        for box in self.boxes():
            try:
                result["boxes"][box] = self.count(box)
            except Exception as e:
                result["problems"].append(
                    "Cannot read " + box + ": " + str(e)
                )
                result["ok"] = False
        return result

    def heal_yourself(self) -> Dict:
        fixed = []
        failed = []

        folder = getattr(self._db.config, "DATA_DIR", None)
        if folder and not os.path.exists(folder):
            try:
                os.makedirs(folder, exist_ok=True)
                fixed.append("Created data folder")
            except Exception as e:
                failed.append(str(e))

        try:
            self._db.snapshot()
            fixed.append("Saved data")
        except Exception as e:
            failed.append("Snapshot: " + str(e))

        for box in self.boxes():
            try:
                self._db.collection(box).rebuild_indexes()
            except Exception:
                pass
        return {"fixed": fixed, "failed": failed}

    def recent_actions(self, n: int = 20) -> List[Dict]:
        return list(self._log[-n:])


__all__ = ["Smart", "Condition", "ScoredResult"]
