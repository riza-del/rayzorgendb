"""
Demo RayzorgenDB — semua fitur
"""

from rayzorgendb import RayzorgenDB


def main():
 db = RayzorgenDB()
 print(" RayzorgenDB — demo lengkap\n")

 users = db.collection("users")
 orders = db.collection("orders")

 # Insert
 u1 = users.insert({
 "name": "Budi", "age": 25,
 "city": "Jakarta", "tags": ["vip"],
 })
 u2 = users.insert({
 "name": "Siti", "age": 30,
 "city": "Bandung", "tags": ["new"],
 })
 u3 = users.insert({
 "name": "Andi", "age": 22,
 "city": "Jakarta", "tags": [],
 })
 print(f" 3 user di-insert")

 # Query chainable
 print("\n Query: Jakarta & age > 23")
 res = users.query() \
 .where("city", "eq", "Jakarta") \
 .where("age", "gt", 23) \
 .order_by("age", desc=True) \
 .all()
 for r in res:
 print(f" - {r['data']['name']} ({r['data']['age']})")

 # Search
 print("\n Search 'bandung'")
 for r in users.search("bandung"):
 print(f" - {r.data['name']}")

 # Index
 users.create_index("city")
 print(f"\n Index: {users.indexes()}")
 print(f" Jakarta: {len(users.find_by('city', 'Jakarta'))}")

 # Aggregate
 print(f"\n Aggregate:")
 print(f" Sum age : {users.aggregate('age', 'sum')}")
 print(f" Avg age : {users.aggregate('age', 'avg'):.1f}")
 print(f" Min/Max : {users.aggregate('age', 'min')} / "
 f"{users.aggregate('age', 'max')}")
 print(f" Group : {users.group_by('city')}")
 print(f" Distinct : {users.distinct('city')}")

 # Transaction
 print("\n Transaksi:")
 tx = db.transaction()
 tx.insert("orders", {"user": "Budi", "total": 500})
 tx.insert("orders", {"user": "Siti", "total": 750})
 tx.commit()
 print(f" Total order: {orders.count()}")

 tx2 = db.transaction()
 tx2.insert("orders", {"user": "Ghost", "total": 999})
 tx2.rollback()
 print(f" Setelah rollback: {orders.count()}")

 # Vector search
 print("\n Vector Search:")
 docs = db.collection("docs")
 docs.insert({"title": "Python", "_vector": [0.9, 0.1, 0.0]})
 docs.insert({"title": "Java", "_vector": [0.8, 0.2, 0.1]})
 docs.insert({"title": "Kopi", "_vector": [0.0, 0.1, 0.9]})
 hits = docs.vector_search([1.0, 0.0, 0.0], top_k=2)
 for h in hits:
 print(f" - {h['data']['title']} "
 f"(score={h['score']})")

 # Events
 print("\n Event listener:")
 counter = {"n": 0}
 def on_ins(p):
 counter["n"] += 1
 print(f" insert di {p['collection']}")
 db.on("record.inserted", on_ins)
 users.insert({"name": "Test", "age": 99})
 print(f" Total event: {counter['n']}")

 # Update many
 print("\n Update many (semua umur +1):")
 n = users.update_many(
 lambda d: "age" in d, {"bonus": True}
 )
 print(f" {n} record di-update")

 # Backup
 users.backup("./users_backup.json")
 print("\n Backup → ./users_backup.json")

 # Stats & health
 print("\n Stats:")
 for k, v in db.stats().items():
 print(f" {k}: {v}")

 print("\n Health:", db.health())

 db.close()
 print("\n Selesai.")


if __name__ == "__main__":
 main()
