"""
RayzorgenDB Benchmark Suite

Comprehensive benchmarks for all operations.
"""

import time
import os
import shutil
import random
from typing import Dict


def format_ms(ms: float) -> str:
    if ms < 1:
        return str(round(ms * 1000, 1)) + " us"
    if ms < 1000:
        return str(round(ms, 2)) + " ms"
    return str(round(ms / 1000, 2)) + " s"


class Benchmark:
    """Benchmark runner for RayzorgenDB."""

    def __init__(self, data_dir: str = "./bench_data"):
        self.data_dir = data_dir
        self.results = []

    def _reset(self):
        if os.path.exists(self.data_dir):
            shutil.rmtree(self.data_dir)

    def _print_header(self, title):
        print()
        print("=" * 60)
        print(title)
        print("=" * 60)

    def _print_result(self, name, ms, extra=""):
        print("  " + name.ljust(35) + format_ms(ms).rjust(12) +
              ("  " + extra if extra else ""))

    def run_all(self, scales=(1000, 10000, 100000)):
        from rayzorgendb import RayzorgenDB, Config

        for n in scales:
            self._run_scale(n)

    def _run_scale(self, n):
        from rayzorgendb import RayzorgenDB, Config

        self._reset()
        self._print_header("SCALE: " + "{:,}".format(n) + " RECORDS")

        # Use large mode if > 50000
        if n >= 50000:
            cfg = Config(DATA_DIR=self.data_dir)
            try:
                cfg.apply_large_mode()
            except AttributeError:
                pass
        else:
            cfg = Config(DATA_DIR=self.data_dir)

        db = RayzorgenDB(cfg)
        users = db.collection("users")

        # 1. Insert
        print()
        print("WRITE")
        print("-" * 60)
        t0 = time.time()
        db.begin_batch()
        for i in range(n):
            users.insert({
                "nama": "user" + str(i),
                "umur": 20 + (i % 40),
                "kota": ["Jakarta", "Bandung", "Surabaya",
                         "Medan", "Yogyakarta"][i % 5],
                "poin": i,
            })
        db.end_batch()
        insert_ms = (time.time() - t0) * 1000
        self._print_result("Insert (batch)",
                           insert_ms,
                           str(round(insert_ms / n * 1000, 0)) + " us/rec")

        # 2. Read by id
        print()
        print("READ")
        print("-" * 60)
        ids = [r.id for r in users.all(limit=100)]
        t0 = time.time()
        for _ in range(10):
            for rid in ids[:100]:
                users.get(rid)
        read_ms = (time.time() - t0) * 1000 / 10 / 100
        self._print_result("Get by id", read_ms)

        # 3. Full scan query
        t0 = time.time()
        result = users.query().where(
            "kota", "eq", "Jakarta"
        ).limit(1000).all()
        scan_ms = (time.time() - t0) * 1000
        self._print_result("Query (no index, limit 1000)", scan_ms)

        # 4. Index
        print()
        print("INDEX")
        print("-" * 60)
        t0 = time.time()
        users.create_index("kota")
        idx_ms = (time.time() - t0) * 1000
        self._print_result("Build hash index", idx_ms)

        # 5. Query with index
        t0 = time.time()
        result = users.find_by_raw("kota", "Jakarta")
        qidx_ms = (time.time() - t0) * 1000
        self._print_result("Query (with index)",
                           qidx_ms,
                           str(len(result)) + " results")

        # 6. B+ Tree
        print()
        print("RANGE")
        print("-" * 60)
        t0 = time.time()
        users.create_sorted_index("umur")
        bt_ms = (time.time() - t0) * 1000
        self._print_result("Build B+ Tree", bt_ms)

        t0 = time.time()
        result = users.range_raw("umur", 30, 40)
        range_ms = (time.time() - t0) * 1000
        self._print_result("Range query (umur 30-40)",
                           range_ms,
                           str(len(result)) + " results")

        # 7. Aggregation
        print()
        print("AGGREGATE")
        print("-" * 60)
        t0 = time.time()
        total = users.aggregate("poin", "sum")
        agg_ms = (time.time() - t0) * 1000
        self._print_result("Sum poin", agg_ms)

        t0 = time.time()
        groups = users.group_by("kota")
        group_ms = (time.time() - t0) * 1000
        self._print_result("Group by kota", group_ms)

        # 8. Full text
        print()
        print("SEARCH")
        print("-" * 60)
        t0 = time.time()
        result = users.search("user50")
        ft_ms = (time.time() - t0) * 1000
        self._print_result("Full-text search", ft_ms)

        # 9. Time travel
        print()
        print("TIME TRAVEL")
        print("-" * 60)
        u = users.all(limit=1)[0]
        t0 = time.time()
        users.update(u.id, {"umur": 99})
        upd_ms = (time.time() - t0) * 1000
        self._print_result("Update (with history)", upd_ms)

        t0 = time.time()
        hist = users.history(u.id)
        hist_ms = (time.time() - t0) * 1000
        self._print_result("Get history", hist_ms)

        # 10. File size
        print()
        print("STORAGE")
        print("-" * 60)
        s = db.stats()
        print("  " + "Snapshot size".ljust(35) +
              (str(round(s["snapshot_bytes"] / 1024 / 1024, 2)) + " MB").rjust(12))
        print("  " + "Per record".ljust(35) +
              (str(round(s["snapshot_bytes"] / n, 1)) + " bytes").rjust(12))

        db.close()


def main():
    print()
    print("RayzorgenDB Benchmark Suite")
    print("=" * 60)
    bench = Benchmark()
    try:
        bench.run_all(scales=(1000, 10000, 100000))
    except KeyboardInterrupt:
        print()
        print("Dibatalkan.")
    finally:
        if os.path.exists(bench.data_dir):
            shutil.rmtree(bench.data_dir)
    print()
    print("=" * 60)
    print("Selesai.")
    print("=" * 60)


if __name__ == "__main__":
    main()
