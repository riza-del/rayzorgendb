"""
RayzorgenDB B+ Tree Index

Self-balancing tree for sorted key access.

Node types:
- Leaf: holds keys and values, links to next leaf
- Internal: holds separator keys and child pointers
"""

from typing import Any, List, Optional, Tuple


class BTreeNode:
    """Base node for B+ Tree."""

    def __init__(self, leaf: bool = False):
        self.leaf = leaf
        self.keys: List[Any] = []
        self.children: List["BTreeNode"] = []
        self.next_leaf: Optional["BTreeNode"] = None


class BTreeLeaf(BTreeNode):
    """Leaf node stores keys and their associated values."""

    def __init__(self):
        super().__init__(leaf=True)
        self.values: List[List[Any]] = []


class BTree:
    """
    B+ Tree index.

    Usage:
        tree = BTree(order=4)
        tree.insert(10, "a")
        tree.insert(20, "b")
        tree.search(10)         # ["a"]
        tree.range(5, 15)       # [(10, ["a"])]
    """

    def __init__(self, order: int = 4):
        if order < 3:
            raise ValueError("order must be >= 3")
        self.order = order
        self.root = BTreeLeaf()
        self._size = 0

    # --------------------------------------------------------
    # Insert
    # --------------------------------------------------------

    def insert(self, key: Any, value: Any):
        """Insert key-value pair. Multiple values per key allowed."""
        leaf = self._find_leaf(key)
        self._insert_into_leaf(leaf, key, value)

        if len(leaf.keys) > self.order - 1:
            self._split_leaf(leaf)

    def _find_leaf(self, key: Any) -> BTreeLeaf:
        node = self.root
        while not node.leaf:
            i = self._find_child_index(node, key)
            node = node.children[i]
        return node

    def _find_child_index(self, node: BTreeNode, key: Any) -> int:
        i = 0
        while i < len(node.keys) and key >= node.keys[i]:
            i += 1
        return i

    def _insert_into_leaf(self, leaf: BTreeLeaf,
                          key: Any, value: Any):
        if key in leaf.keys:
            idx = leaf.keys.index(key)
            if value not in leaf.values[idx]:
                leaf.values[idx].append(value)
                self._size += 1
            return

        i = 0
        while i < len(leaf.keys) and leaf.keys[i] < key:
            i += 1

        leaf.keys.insert(i, key)
        leaf.values.insert(i, [value])
        self._size += 1

    def _split_leaf(self, leaf: BTreeLeaf):
        mid = len(leaf.keys) // 2

        right = BTreeLeaf()
        right.keys = leaf.keys[mid:]
        right.values = leaf.values[mid:]
        right.next_leaf = leaf.next_leaf

        leaf.keys = leaf.keys[:mid]
        leaf.values = leaf.values[:mid]
        leaf.next_leaf = right

        up_key = right.keys[0]
        self._insert_into_parent(leaf, up_key, right)

    def _insert_into_parent(self, left: BTreeNode,
                            key: Any, right: BTreeNode):
        if left is self.root:
            new_root = BTreeNode(leaf=False)
            new_root.keys = [key]
            new_root.children = [left, right]
            self.root = new_root
            return

        parent = self._find_parent(self.root, left)
        if parent is None:
            return

        i = parent.children.index(left)
        parent.keys.insert(i, key)
        parent.children.insert(i + 1, right)

        if len(parent.keys) > self.order - 1:
            self._split_internal(parent)

    def _find_parent(self, node: BTreeNode,
                     child: BTreeNode) -> Optional[BTreeNode]:
        if node.leaf:
            return None
        for c in node.children:
            if c is child:
                return node
            if not c.leaf:
                r = self._find_parent(c, child)
                if r is not None:
                    return r
        return None

    def _split_internal(self, node: BTreeNode):
        mid = len(node.keys) // 2
        up_key = node.keys[mid]

        right = BTreeNode(leaf=False)
        right.keys = node.keys[mid + 1:]
        right.children = node.children[mid + 1:]

        node.keys = node.keys[:mid]
        node.children = node.children[:mid + 1]

        self._insert_into_parent(node, up_key, right)

    # --------------------------------------------------------
    # Search
    # --------------------------------------------------------

    def search(self, key: Any) -> List[Any]:
        leaf = self._find_leaf(key)
        if key in leaf.keys:
            idx = leaf.keys.index(key)
            return list(leaf.values[idx])
        return []

    def contains(self, key: Any) -> bool:
        return len(self.search(key)) > 0

    # --------------------------------------------------------
    # Range Query
    # --------------------------------------------------------

    def range(self, start: Any = None,
              end: Any = None,
              inclusive_end: bool = True) -> List[Tuple[Any, Any]]:
        results = []

        if start is None:
            leaf = self._leftmost_leaf()
        else:
            leaf = self._find_leaf(start)

        while leaf is not None:
            for i, key in enumerate(leaf.keys):
                if start is not None and key < start:
                    continue
                if end is not None:
                    if inclusive_end and key > end:
                        return results
                    if not inclusive_end and key >= end:
                        return results
                for v in leaf.values[i]:
                    results.append((key, v))
            leaf = leaf.next_leaf

        return results

    def _leftmost_leaf(self) -> BTreeLeaf:
        node = self.root
        while not node.leaf:
            node = node.children[0]
        return node

    def min_key(self) -> Optional[Any]:
        leaf = self._leftmost_leaf()
        return leaf.keys[0] if leaf.keys else None

    def max_key(self) -> Optional[Any]:
        node = self.root
        while not node.leaf:
            node = node.children[-1]
        return node.keys[-1] if node.keys else None

    # --------------------------------------------------------
    # Delete
    # --------------------------------------------------------

    def bulk_load(self, items):
        """
        Bulk load dari list (key, value) yang belum tentu sorted.
        Build tree bottom-up - jauh lebih cepat dari insert satu-satu.
        """
        if not items:
            self.root = BTreeLeaf()
            self._size = 0
            return

        # Sort semua
        items = sorted(items, key=lambda x: x[0])

        # Group by key (kalau ada duplicate keys)
        grouped = []
        current_key = None
        current_values = []
        for key, value in items:
            if current_key is None or key == current_key:
                current_key = key
                current_values.append(value)
            else:
                grouped.append((current_key, current_values))
                current_key = key
                current_values = [value]
        if current_key is not None:
            grouped.append((current_key, current_values))

        # Bagi jadi leaf chunks
        max_leaf = self.order - 1
        leaves = []
        for i in range(0, len(grouped), max_leaf):
            chunk = grouped[i:i + max_leaf]
            leaf = BTreeLeaf()
            for k, vals in chunk:
                leaf.keys.append(k)
                leaf.values.append(list(vals))
                self._size += len(vals)
            leaves.append(leaf)

        # Link leaf chain
        for i in range(len(leaves) - 1):
            leaves[i].next_leaf = leaves[i + 1]

        # Kalau cuma 1 leaf, selesai
        if len(leaves) == 1:
            self.root = leaves[0]
            return

        # Build internal nodes bottom-up
        max_internal = self.order - 1
        current_level = leaves

        while len(current_level) > 1:
            next_level = []
            i = 0
            while i < len(current_level):
                # Ambil maksimal (order) children per internal node
                chunk = current_level[i:i + self.order]
                i += self.order

                parent = BTreeNode(leaf=False)
                parent.children = chunk
                # Separator = first key of each child, kecuali anak pertama
                parent.keys = [
                    c.keys[0] for c in chunk[1:]
                    if c.keys
                ]
                next_level.append(parent)

            current_level = next_level

        self.root = current_level[0]

    def delete(self, key: Any, value: Any = None) -> bool:
        leaf = self._find_leaf(key)
        if key not in leaf.keys:
            return False

        idx = leaf.keys.index(key)

        if value is None:
            removed = len(leaf.values[idx])
            del leaf.keys[idx]
            del leaf.values[idx]
            self._size -= removed
            return True
        else:
            if value in leaf.values[idx]:
                leaf.values[idx].remove(value)
                self._size -= 1
                if not leaf.values[idx]:
                    del leaf.keys[idx]
                    del leaf.values[idx]
                return True
        return False

    # --------------------------------------------------------
    # Iteration
    # --------------------------------------------------------

    def all_items(self) -> List[Tuple[Any, Any]]:
        return self.range(None, None)

    def keys(self) -> List[Any]:
        return [k for k, _ in self.all_items()]

    def values(self) -> List[Any]:
        return [v for _, v in self.all_items()]

    # --------------------------------------------------------
    # Info
    # --------------------------------------------------------

    def size(self) -> int:
        return self._size

    def clear(self):
        self.root = BTreeLeaf()
        self._size = 0

    def height(self) -> int:
        h = 0
        node = self.root
        while not node.leaf:
            h += 1
            node = node.children[0]
        return h

    def stats(self) -> dict:
        return {
            "size": self._size,
            "height": self.height(),
            "order": self.order,
            "root_keys": len(self.root.keys),
        }


__all__ = ["BTree", "BTreeNode", "BTreeLeaf"]
