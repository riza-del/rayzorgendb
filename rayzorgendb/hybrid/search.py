"""
RayzorgenDB Hybrid Search

Combine sparse (keyword) and dense (vector) retrieval.

Sparse: BM25 for keyword exact matching
Dense: Cosine similarity for semantic matching
Fusion: Reciprocal Rank Fusion (RRF)

Usage:
    hs = HybridSearch()
    hs.add_document("doc1", "text about python", [0.1, 0.2])
    results = hs.search("python", [0.1, 0.2], k=5)
"""

import math
import re
import threading
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple


def tokenize(text: str) -> List[str]:
    """
    Lowercase, split on non-alphanumeric,
    and split letter/digit boundaries.
    Example: "Doc0" -> ["doc", "0"]
    """
    text = text.lower()
    # Split on non-alphanumeric first
    parts = re.findall(r"[a-z0-9]+", text)
    # Then split letter/digit boundaries
    tokens = []
    for p in parts:
        tokens.extend(re.findall(r"[a-z]+|[0-9]+", p))
    return tokens


class BM25:
    """
    Okapi BM25 sparse retrieval.

    Params:
        k1: term frequency saturation (default 1.5)
        b: length normalization (default 0.75)
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        # doc_id -> tokens
        self._docs: Dict[str, List[str]] = {}
        # doc_id -> token frequencies
        self._tf: Dict[str, Counter] = {}
        # doc_id -> length
        self._lengths: Dict[str, int] = {}
        # term -> set of doc_ids
        self._postings: Dict[str, set] = {}
        self._avg_len = 0.0
        self._lock = threading.RLock()

    def add(self, doc_id: str, text: str):
        with self._lock:
            if doc_id in self._docs:
                self.remove(doc_id)
            tokens = tokenize(text)
            self._docs[doc_id] = tokens
            self._tf[doc_id] = Counter(tokens)
            self._lengths[doc_id] = len(tokens)
            for token in set(tokens):
                self._postings.setdefault(token, set()).add(doc_id)
            self._update_avg_len()

    def remove(self, doc_id: str):
        with self._lock:
            if doc_id not in self._docs:
                return
            tokens = set(self._docs[doc_id])
            for token in tokens:
                if token in self._postings:
                    self._postings[token].discard(doc_id)
                    if not self._postings[token]:
                        del self._postings[token]
            del self._docs[doc_id]
            del self._tf[doc_id]
            del self._lengths[doc_id]
            self._update_avg_len()

    def _update_avg_len(self):
        if self._docs:
            self._avg_len = (
                sum(self._lengths.values()) / len(self._docs)
            )
        else:
            self._avg_len = 0.0

    def search(self, query: str, k: int = 10) -> List[Tuple[str, float]]:
        """Return top-k (doc_id, score)."""
        with self._lock:
            query_tokens = tokenize(query)
            if not query_tokens:
                return []

            n_docs = len(self._docs)
            scores: Dict[str, float] = {}

            for token in query_tokens:
                doc_ids = self._postings.get(token, set())
                if not doc_ids:
                    continue
                df = len(doc_ids)
                idf = math.log(
                    (n_docs - df + 0.5) / (df + 0.5) + 1.0
                )
                for doc_id in doc_ids:
                    tf = self._tf[doc_id].get(token, 0)
                    doc_len = self._lengths[doc_id]
                    norm = 1 - self.b + self.b * (
                        doc_len / self._avg_len
                        if self._avg_len else 1
                    )
                    score = idf * (
                        tf * (self.k1 + 1)
                    ) / (tf + self.k1 * norm)
                    scores[doc_id] = scores.get(doc_id, 0) + score

            ranked = sorted(
                scores.items(), key=lambda x: x[1], reverse=True
            )
            return ranked[:k]

    def size(self) -> int:
        return len(self._docs)


class HybridSearch:
    """
    Hybrid retrieval: BM25 + vector.

    Fusion method: Reciprocal Rank Fusion (RRF).
    RRF score = sum(1 / (k + rank)) over each ranker.
    """

    def __init__(self, rrf_k: int = 60,
                 sparse_weight: float = 0.5,
                 dense_weight: float = 0.5):
        self.rrf_k = rrf_k
        self.sparse_weight = sparse_weight
        self.dense_weight = dense_weight
        self.bm25 = BM25()
        self._vectors: Dict[str, List[float]] = {}
        self._texts: Dict[str, str] = {}
        self._lock = threading.RLock()

    # --------------------------------------------------------
    # Add documents
    # --------------------------------------------------------

    def add_document(self, doc_id: str, text: str,
                     vector: List[float] = None):
        with self._lock:
            self._texts[doc_id] = text
            self.bm25.add(doc_id, text)
            if vector is not None:
                self._vectors[doc_id] = list(vector)

    def remove_document(self, doc_id: str):
        with self._lock:
            self.bm25.remove(doc_id)
            self._texts.pop(doc_id, None)
            self._vectors.pop(doc_id, None)

    # --------------------------------------------------------
    # Search
    # --------------------------------------------------------

    def search(self, query: str = "",
               query_vector: List[float] = None,
               k: int = 10,
               method: str = "hybrid") -> List[Dict]:
        """
        Search documents.

        method:
            "sparse" -> BM25 only
            "dense"  -> vector only
            "hybrid" -> both with RRF (default)
        """
        with self._lock:
            if method == "sparse":
                return self._sparse_search(query, k)
            if method == "dense":
                return self._dense_search(query_vector, k)
            return self._hybrid_search(query, query_vector, k)

    def _sparse_search(self, query: str, k: int) -> List[Dict]:
        results = self.bm25.search(query, k)
        return [
            {
                "id": doc_id,
                "score": round(score, 4),
                "text": self._texts.get(doc_id, ""),
                "source": "sparse",
            }
            for doc_id, score in results
        ]

    def _dense_search(self, query_vector: List[float],
                      k: int) -> List[Dict]:
        if not query_vector or not self._vectors:
            return []
        scored = []
        for doc_id, vec in self._vectors.items():
            if len(vec) != len(query_vector):
                continue
            sim = self._cosine(query_vector, vec)
            scored.append((doc_id, sim))
        scored.sort(key=lambda x: x[1], reverse=True)
        return [
            {
                "id": doc_id,
                "score": round(score, 4),
                "text": self._texts.get(doc_id, ""),
                "source": "dense",
            }
            for doc_id, score in scored[:k]
        ]

    def _hybrid_search(self, query: str,
                       query_vector: List[float],
                       k: int) -> List[Dict]:
        # Get top candidates from each (wide net)
        sparse_results = self.bm25.search(query, k * 3)
        dense_results = self._dense_search_raw(
            query_vector, k * 3
        )

        # RRF fusion
        rrf_scores: Dict[str, float] = {}

        for rank, (doc_id, _) in enumerate(sparse_results):
            rrf_scores[doc_id] = (
                rrf_scores.get(doc_id, 0) +
                self.sparse_weight / (self.rrf_k + rank + 1)
            )

        for rank, (doc_id, _) in enumerate(dense_results):
            rrf_scores[doc_id] = (
                rrf_scores.get(doc_id, 0) +
                self.dense_weight / (self.rrf_k + rank + 1)
            )

        ranked = sorted(
            rrf_scores.items(),
            key=lambda x: x[1],
            reverse=True,
        )[:k]

        return [
            {
                "id": doc_id,
                "score": round(score, 6),
                "text": self._texts.get(doc_id, ""),
                "source": "hybrid",
            }
            for doc_id, score in ranked
        ]

    def _dense_search_raw(self, query_vector: List[float],
                          k: int) -> List[Tuple[str, float]]:
        if not query_vector or not self._vectors:
            return []
        scored = []
        for doc_id, vec in self._vectors.items():
            if len(vec) != len(query_vector):
                continue
            sim = self._cosine(query_vector, vec)
            scored.append((doc_id, sim))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]

    # --------------------------------------------------------
    # Helpers
    # --------------------------------------------------------

    @staticmethod
    def _cosine(a: List[float], b: List[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = 0.0
        na = 0.0
        nb = 0.0
        for x, y in zip(a, b):
            dot += x * y
            na += x * x
            nb += y * y
        if na == 0 or nb == 0:
            return 0.0
        return dot / (math.sqrt(na) * math.sqrt(nb))

    def stats(self) -> Dict:
        return {
            "documents": len(self._texts),
            "with_vectors": len(self._vectors),
            "bm25_docs": self.bm25.size(),
            "rrf_k": self.rrf_k,
            "sparse_weight": self.sparse_weight,
            "dense_weight": self.dense_weight,
        }

    def clear(self):
        with self._lock:
            self.bm25 = BM25(k1=self.bm25.k1, b=self.bm25.b)
            self._vectors.clear()
            self._texts.clear()


__all__ = ["HybridSearch", "BM25", "tokenize"]
