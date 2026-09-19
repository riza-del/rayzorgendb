"""
RayzorgenDB CLI
python -m rayzorgendb.cli.main <command>
"""

import sys
import json
import argparse

from rayzorgendb.api import RayzorgenDB


def _out(data):
    print(json.dumps(data, indent=2, default=str))


def cmd_stats(args):
    _out(RayzorgenDB().stats())


def cmd_health(args):
    _out(RayzorgenDB().health())


def cmd_collections(args):
    for c in RayzorgenDB().collections():
        print(c)


def cmd_query(args):
    db = RayzorgenDB()
    if not db.has_collection(args.collection):
        print(f"Koleksi '{args.collection}' tidak ada.")
        return
    q = db.collection(args.collection).query()
    for f in args.filter or []:
        try:
            field, op, value = f.split(":", 2)
        except ValueError:
            print(f"Filter salah: {f}")
            return
        # Auto-cast number
        try:
            value = int(value)
        except ValueError:
            try:
                value = float(value)
            except ValueError:
                if value.lower() in ("true", "false"):
                    value = value.lower() == "true"
        q = q.where(field, op, value)
    if args.order:
        q = q.order_by(args.order, args.desc)
    q = q.limit(args.limit)
    _out(q.all())


def cmd_insert(args):
    db = RayzorgenDB()
    try:
        data = json.loads(args.json)
    except json.JSONDecodeError as e:
        print(f"JSON salah: {e}")
        return
    rec = db.collection(args.collection).insert(data)
    _out(rec.to_dict())


def cmd_search(args):
    db = RayzorgenDB()
    if not db.has_collection(args.collection):
        print(f"Koleksi '{args.collection}' tidak ada.")
        return
    results = db.collection(args.collection).search(args.keyword)
    _out([r.to_dict() for r in results])


def cmd_aggregate(args):
    db = RayzorgenDB()
    if not db.has_collection(args.collection):
        print(f"Koleksi '{args.collection}' tidak ada.")
        return
    value = db.collection(args.collection).aggregate(
        args.field, args.op
    )
    _out({"value": value})


def cmd_index(args):
    db = RayzorgenDB()
    coll = db.collection(args.collection)
    coll.create_index(args.field)
    _out({"indexes": coll.indexes()})


def cmd_delete(args):
    db = RayzorgenDB()
    ok = db.collection(args.collection).delete(args.id)
    _out({"deleted": ok})


def cmd_drop(args):
    db = RayzorgenDB()
    ok = db.drop_collection(args.collection)
    _out({"dropped": ok})


def main():
    parser = argparse.ArgumentParser(
        prog="rayzorgendb",
        description="RayzorgenDB CLI",
    )
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("stats").set_defaults(func=cmd_stats)
    sub.add_parser("health").set_defaults(func=cmd_health)
    sub.add_parser("collections").set_defaults(
        func=cmd_collections
    )

    p = sub.add_parser("query")
    p.add_argument("collection")
    p.add_argument("--filter", action="append",
                   help="field:op:value")
    p.add_argument("--order")
    p.add_argument("--desc", action="store_true")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_query)

    p = sub.add_parser("insert")
    p.add_argument("collection")
    p.add_argument("json")
    p.set_defaults(func=cmd_insert)

    p = sub.add_parser("search")
    p.add_argument("collection")
    p.add_argument("keyword")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("aggregate")
    p.add_argument("collection")
    p.add_argument("field")
    p.add_argument("--op", default="sum")
    p.set_defaults(func=cmd_aggregate)

    p = sub.add_parser("index")
    p.add_argument("collection")
    p.add_argument("field")
    p.set_defaults(func=cmd_index)

    p = sub.add_parser("delete")
    p.add_argument("collection")
    p.add_argument("id")
    p.set_defaults(func=cmd_delete)

    p = sub.add_parser("drop")
    p.add_argument("collection")
    p.set_defaults(func=cmd_drop)

    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
