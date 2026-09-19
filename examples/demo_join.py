"""
Demo JOIN RayzorgenDB
"""

from rayzorgendb import RayzorgenDB, Config


def main():
 import os
 import shutil
 if os.path.exists("./demo_join_data"):
 shutil.rmtree("./demo_join_data")

 db = RayzorgenDB(Config(DATA_DIR="./demo_join_data"))
 print(" RayzorgenDB — Demo JOIN\n")

 users = db.collection("users")
 orders = db.collection("orders")
 products = db.collection("products")

 # Setup
 budi = users.insert({"name": "Budi", "age": 25, "city": "Jakarta"})
 siti = users.insert({"name": "Siti", "age": 30, "city": "Bandung"})
 andi = users.insert({"name": "Andi", "age": 22, "city": "Jakarta"})

 kopi = products.insert({"name": "Kopi", "price": 20000})
 teh = products.insert({"name": "Teh", "price": 15000})

 orders.insert({"user_id": budi.id, "product_id": kopi.id,
 "total": 50000, "qty": 2})
 orders.insert({"user_id": budi.id, "product_id": teh.id,
 "total": 15000, "qty": 1})
 orders.insert({"user_id": siti.id, "product_id": kopi.id,
 "total": 40000, "qty": 2})
 print(" Data siap: 3 user, 2 produk, 3 order\n")

 # ─── LEFT JOIN ──────────────────────────────
 print("=" * 55)
 print("1. LEFT JOIN: semua user dengan ordernya")
 print("=" * 55)
 result = users.join("orders", on=("id", "user_id")).all()
 for r in result:
 name = r["_joined"]["users"]["data"]["name"]
 ords = r["_joined"]["orders"]
 if ords:
 items = ", ".join(
 f"{o['data']['qty']}x (Rp {o['data']['total']:,})"
 for o in ords
 )
 else:
 items = "(belum ada order)"
 print(f" {name:8s} → {items}")

 # ─── INNER JOIN ─────────────────────────────
 print("\n" + "=" * 55)
 print("2. INNER JOIN: hanya user yang punya order")
 print("=" * 55)
 result = users.join(
 "orders", on=("id", "user_id"),
 join_type="inner",
 ).all()
 for r in result:
 name = r["_joined"]["users"]["data"]["name"]
 n_ord = len(r["_joined"]["orders"])
 print(f" {name:8s} → {n_ord} order")

 # ─── Filter Join ────────────────────────────
 print("\n" + "=" * 55)
 print("3. JOIN + WHERE: order dari user > 24 tahun")
 print("=" * 55)
 result = users.join(
 "orders", on=("id", "user_id")
 ).where("users.age", "gt", 24).all()
 for r in result:
 name = r["_joined"]["users"]["data"]["name"]
 age = r["_joined"]["users"]["data"]["age"]
 print(f" {name} ({age} tahun)")

 # ─── Select ─────────────────────────────────
 print("\n" + "=" * 55)
 print("4. SELECT: projection custom")
 print("=" * 55)
 result = users.join(
 "orders", on=("id", "user_id")
 ).select(
 nama="users.name",
 kota="users.city",
 ).all()
 for r in result:
 print(f" {r['nama']:8s} ({r['kota']})")

 # ─── Group By ───────────────────────────────
 print("\n" + "=" * 55)
 print("5. GROUP BY: jumlah user per kota")
 print("=" * 55)
 result = users.join(
 "orders", on=("id", "user_id")
 ).group_by("users.city")
 for kota, jumlah in result.items():
 print(f" {kota}: {jumlah} user")

 # ─── Multi JOIN ─────────────────────────────
 print("\n" + "=" * 55)
 print("6. MULTI JOIN: users → orders → products")
 print("=" * 55)
 result = users.join_many([
 {"collection": "orders",
 "left_key": "id",
 "right_key": "user_id"},
 {"collection": "products",
 "left_key": "orders.product_id",
 "right_key": "id"},
 ]).all()

 for r in result:
 name = r["_joined"]["users"]["data"]["name"]
 prods = r["_joined"].get("products", [])
 names = [p["data"]["name"] for p in prods]
 print(f" {name:8s} → produk: {names if names else '[]'}")

 # ─── Complex Query ──────────────────────────
 print("\n" + "=" * 55)
 print("7. COMPLEX: group by kota, filter, order")
 print("=" * 55)
 result = users.join(
 "orders", on=("id", "user_id")
 ).where("users.city", "eq", "Jakarta") \
 .order_by("users.age", desc=True) \
 .all()
 for r in result:
 u = r["_joined"]["users"]["data"]
 n = len(r["_joined"]["orders"])
 print(f" {u['name']} ({u['age']}) — {n} order")

 db.close()
 print("\n Demo selesai!")


if __name__ == "__main__":
 main()
