"""
YCSB Benchmark for RayzorgenDB

Yahoo! Cloud Serving Benchmark.
Workloads A-F sesuai standar industri.
"""

import random
import time
import os
import shutil
from typing import Dict, List


def percentile(sorted_list, p):
    if not sorted_list:
        return 0
    idx = int(len(sorted_list) * p)
    if idx >= len(sorted_list):
        idx = len(sorted_list) - 1
    return sorted_list[idx]


class YCSB:
    """YCSB benchmark runner."""

    def __init__(self, db, collection: str = "ycsb"):
        self.db = db
        self.collection = collection
        self.ids: List[str] = []

    def load(self, n: int):
        """Load n records."""
        print("  Loading " + str(n) + " records...")
        t0 = time.time()
        coll = self.db.collection(self.collection)
        self.db.begin_batch()
        for i in range(n):
            rec = coll.insert({
                "field0": "value_" + str(i),
                "field1": i,
                "field2": "text_" + str(i * 7),
                "field3": i % 100,
            })
            self.ids.append(rec.id)
        self.db.end_batch()
        t1 = time.time()
        return {
            "records": n,
            "duration_sec": round(t1 - t0, 2),
            "rate_per_sec": int(n / (t1 - t0)),
        }

    def run(self, name: str, n_ops: int,
            read_pct: float, update_pct: float,
            insert_pct: float = 0.0,
            scan_pct: float = 0.0) -> Dict:
        """Run one workload."""
        coll = self.db.collection(self.collection)
        latencies = []

        t0 = time.time()
        for _ in range(n_ops):
            r = random.random()
            op_start = time.time()

            if r < read_pct:
                rid = random.choice(self.ids)
                coll.get(rid)
            elif r < read_pct + update_pct:
                rid = random.choice(self.ids)
                coll.update(rid, {
                    "field1": random.randint(0, 1000000)
                })
            elif r < read_pct + update_pct + insert_pct:
                rec = coll.insert({
                    "field0": "new_" + str(random.randint(0, 99999)),
                    "field1": random.randint(0, 1000000),
                })
                self.ids.append(rec.id)
            elif r < read_pct + update_pct + insert_pct + scan_pct:
                limit = random.randint(10, 100)
                coll.query().limit(limit).all()

            latencies.append((time.time() - op_start) * 1000)

        t1 = time.time()
        total = t1 - t0
        latencies.sort()

        return {
            "workload": name,
            "operations": n_ops,
            "duration_sec": round(total, 3),
            "throughput": int(n_ops / total),
            "avg_ms": round(sum(latencies) / len(latencies), 3),
            "p50_ms": round(percentile(latencies, 0.50), 3),
            "p95_ms": round(percentile(latencies, 0.95), 3),
            "p99_ms": round(percentile(latencies, 0.99), 3),
            "max_ms": round(latencies[-1], 3),
        }


WORKLOADS = [
    ("A (50R/50U)",  0.50, 0.50, 0.0, 0.0),
    ("B (95R/5U)",   0.95, 0.05, 0.0, 0.0),
    ("C (100R)",     1.00, 0.00, 0.0, 0.0),
    ("D (95R/5I)",   0.95, 0.00, 0.05, 0.0),
    ("E (95Scan/5I)", 0.00, 0.00, 0.05, 0.95),
    ("F (50R/50RMW)", 0.50, 0.50, 0.0, 0.0),
]


def run_benchmark(data_dir: str = "./ycsb_data",
                  n_records: int = 100000,
                  n_ops: int = 50000):
    from rayzorgendb import RayzorgenDB, Config

    if os.path.exists(data_dir):
        shutil.rmtree(data_dir)

    print()
    print("=" * 70)
    print("YCSB BENCHMARK - RayzorgenDB")
    print("=" * 70)
    print("Records  : " + "{:,}".format(n_records))
    print("Ops/workload: " + "{:,}".format(n_ops))
    print()

    cfg = Config(DATA_DIR=data_dir)
    cfg.apply_large_mode()

    db = RayzorgenDB(cfg)
    ycsb = YCSB(db)

    # Load
    load_stats = ycsb.load(n_records)
    print("  Loaded: " + str(load_stats["records"]) +
          " in " + str(load_stats["duration_sec"]) + "s (" +
          "{:,}".format(load_stats["rate_per_sec"]) + " rec/s)")
    print()

    # Run workloads
    print("-" * 70)
    print("WORKLOADS")
    print("-" * 70)
    print()

    results = []
    for name, read_pct, update_pct, insert_pct, scan_pct in WORKLOADS:
        r = ycsb.run(
            name, n_ops, read_pct, update_pct,
            insert_pct, scan_pct,
        )
        results.append(r)
        print("  " + r["workload"].ljust(18) +
              "throughput=" + "{:,}".format(r["throughput"]).rjust(10) +
              " ops/sec" +
              "  p50=" + str(r["p50_ms"]).rjust(7) +
              "ms" +
              "  p99=" + str(r["p99_ms"]).rjust(7) + "ms")

    db.close()

    # Summary
    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print()
    print("Workload".ljust(20) +
          "Throughput".rjust(15) +
          "p50".rjust(10) +
          "p95".rjust(10) +
          "p99".rjust(10))
    print("-" * 70)
    for r in results:
        print(r["workload"].ljust(20) +
              "{:,}".format(r["throughput"]).rjust(15) +
              str(r["p50_ms"]).rjust(10) +
              str(r["p95_ms"]).rjust(10) +
              str(r["p99_ms"]).rjust(10))
    print()

    return results


if __name__ == "__main__":
    run_benchmark()
