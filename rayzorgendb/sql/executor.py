"""
RayzorgenDB SQL Executor

Execute parsed AST against storage engine.
"""

import re
from typing import Any, Dict, List, Optional
from rayzorgendb.sql.parser import (
    CaseWhen, Coalesce, Union, Subquery,
    Select, Insert, Update, Delete, CreateTable,
    CreateIndex, DropTable, DropIndex,
    Column, Star, Literal, BinOp, UnaryOp,
    FuncCall, InList, Like, Between, IsNull,
    SQLError,
)


class Executor:
    """Execute SQL AST against a RayzorgenDB instance."""

    def __init__(self, db):
        self.db = db

    def execute(self, node) -> Dict:
        if isinstance(node, Select):
            return self.execute_select(node)
        if isinstance(node, Insert):
            return self.execute_insert(node)
        if isinstance(node, Update):
            return self.execute_update(node)
        if isinstance(node, Delete):
            return self.execute_delete(node)
        if isinstance(node, CreateTable):
            return self.execute_create_table(node)
        if isinstance(node, CreateIndex):
            return self.execute_create_index(node)
        if isinstance(node, DropTable):
            return self.execute_drop_table(node)
        if isinstance(node, DropIndex):
            return self.execute_drop_index(node)
        raise SQLError("Unknown node: " + type(node).__name__)

    # --------------------------------------------------------
    # SELECT
    # --------------------------------------------------------

    def execute_select(self, node: Select) -> Dict:
        if not node.table:
            # SELECT without FROM
            rows = [{}]
        else:
            if not self.db.has_collection(node.table):
                raise SQLError(
                    "Table '" + node.table + "' does not exist"
                )
            rows = [
                r.to_dict() for r
                in self.db.collection(node.table).all()
            ]

        # Add table name prefix to each row for JOIN handling
        for r in rows:
            r["_table"] = node.table

        # JOINs
        for join in node.joins:
            rows = self.execute_join(rows, node.table, join)

        # WHERE
        if node.where is not None:
            rows = [
                r for r in rows
                if self.eval_expr(node.where, r)
            ]

        # Check if aggregate query
        has_agg = self._has_aggregate(node.columns)
        if node.group_by or has_agg:
            return self.execute_aggregate(node, rows)

        # Projection
        result = [self.project_row(r, node.columns) for r in rows]

        # DISTINCT
        if node.distinct:
            seen = []
            for r in result:
                if r not in seen:
                    seen.append(r)
            result = seen

        # ORDER BY
        if node.order_by:
            for col, desc in reversed(node.order_by):
                result.sort(
                    key=lambda r: self._sort_key(
                        self.eval_order_expr(col, r)
                    ),
                    reverse=desc,
                )

        # OFFSET / LIMIT
        if node.offset:
            result = result[node.offset:]
        if node.limit is not None:
            result = result[:node.limit]

        return {
            "columns": self._column_names(node.columns),
            "rows": result,
            "count": len(result),
        }

    def _sort_key(self, v):
        if v is None:
            return (1, 0)
        if isinstance(v, (int, float)):
            return (0, v)
        return (0, str(v))

    def _column_names(self, columns):
        names = []
        for c in columns:
            if isinstance(c, Star):
                names.append("*")
            elif isinstance(c, tuple) and c[0] == "alias":
                names.append(c[2])
            elif isinstance(c, Column):
                names.append(c.name)
            elif isinstance(c, FuncCall):
                names.append(c.name.lower())
            elif isinstance(c, CaseWhen):
                names.append("case")
            elif isinstance(c, Coalesce):
                names.append("coalesce")
            elif isinstance(c, BinOp):
                names.append("expr")
            else:
                names.append("col")
        return names

    def _has_aggregate(self, columns):
        for c in columns:
            if isinstance(c, FuncCall):
                if c.name in ("COUNT", "SUM", "AVG",
                               "MIN", "MAX"):
                    return True
        return False

    def project_row(self, row: Dict, columns) -> Dict:
        result = {}
        data = row.get("data", row)

        for c in columns:
            if isinstance(c, Star):
                for k, v in data.items():
                    if k not in result:
                        result[k] = v
            elif isinstance(c, tuple) and c[0] == "alias":
                _, expr, alias = c
                result[alias] = self.eval_expr(expr, row)
            elif isinstance(c, Column):
                key = c.name
                if key in data:
                    result[c.name] = data[key]
                else:
                    result[c.name] = None
            elif isinstance(c, FuncCall):
                result[c.name.lower()] = self.eval_expr(c, row)
            elif isinstance(c, CaseWhen):
                result["case"] = self.eval_expr(c, row)
            elif isinstance(c, Coalesce):
                result["coalesce"] = self.eval_expr(c, row)
            elif isinstance(c, BinOp):
                result["expr"] = self.eval_expr(c, row)
            else:
                result["col"] = self.eval_expr(c, row)

        return result

    def eval_order_expr(self, expr, row):
        if isinstance(expr, Column):
            data = row.get("data", row)
            return data.get(expr.name)
        return self.eval_expr(expr, row)

    # --------------------------------------------------------
    # JOIN
    # --------------------------------------------------------

    def execute_join(self, left_rows, left_table, join) -> List[Dict]:
        if not self.db.has_collection(join.table):
            raise SQLError(
                "Table '" + join.table + "' does not exist"
            )
        right_rows = [
            r.to_dict() for r
            in self.db.collection(join.table).all()
        ]
        for r in right_rows:
            r["_table"] = join.table

        right_alias = join.alias or join.table
        result = []
        matched_right = set()

        for lrow in left_rows:
            found = False
            for ridx, rrow in enumerate(right_rows):
                merged = self._merge_row(
                    lrow, rrow, left_table, right_alias
                )
                if self.eval_expr(join.on_left, merged) ==                         self.eval_expr(join.on_right, merged):
                    result.append(merged)
                    matched_right.add(ridx)
                    found = True
            if not found and join.type == "LEFT":
                empty = self._empty_row(right_rows, right_alias)
                merged = self._merge_row(
                    lrow, empty, left_table, right_alias
                )
                result.append(merged)

        if join.type == "RIGHT":
            for ridx, rrow in enumerate(right_rows):
                if ridx not in matched_right:
                    empty = self._empty_row(
                        left_rows, left_table
                    )
                    merged = self._merge_row(
                        empty, rrow, left_table, right_alias
                    )
                    result.append(merged)

        return result

    def _merge_row(self, left, right, left_table, right_table):
        merged = {
            "_table_left": left_table,
            "_table_right": right_table,
        }
        # Left data
        ldata = left.get("data", {})
        for k, v in ldata.items():
            merged[left_table + "." + k] = v
        if "_id" in left or "id" in left:
            merged[left_table + ".id"] = left.get("id")
        # Right data
        rdata = right.get("data", {})
        for k, v in rdata.items():
            merged[right_table + "." + k] = v
        if "id" in right:
            merged[right_table + ".id"] = right.get("id")
        # Keep original structure for compatibility
        merged["_left"] = left
        merged["_right"] = right
        return merged

    def _empty_row(self, rows, table):
        if rows:
            return {
                "id": None, "data": {},
                "_table": table,
            }
        return {"id": None, "data": {}, "_table": table}

    # --------------------------------------------------------
    # INSERT
    # --------------------------------------------------------

    def execute_insert(self, node: Insert) -> Dict:
        collection = self.db.collection(node.table)
        inserted = 0

        for value_row in node.values:
            data = {}
            for i, val in enumerate(value_row):
                key = (
                    node.columns[i] if i < len(node.columns)
                    else "field" + str(i)
                )
                data[key] = self.eval_literal(val)
            collection.insert(data)
            inserted += 1

        return {
            "inserted": inserted,
            "table": node.table,
        }

    def eval_literal(self, expr):
        if isinstance(expr, Literal):
            return expr.value
        if isinstance(expr, Column):
            return expr.name
        return None

    # --------------------------------------------------------
    # UPDATE
    # --------------------------------------------------------

    def execute_update(self, node: Update) -> Dict:
        if not self.db.has_collection(node.table):
            raise SQLError(
                "Table '" + node.table + "' does not exist"
            )
        collection = self.db.collection(node.table)

        # Build update dict
        update_data = {}
        for col, expr in node.assignments:
            update_data[col] = self.eval_literal(expr)

        # Find matching records
        if node.where is None:
            matched = collection.all()
        else:
            matched = []
            for r in collection.all():
                row = r.to_dict()
                if self.eval_expr(node.where, row):
                    matched.append(r)

        # Update
        for r in matched:
            collection.update(r.id, update_data)

        return {
            "updated": len(matched),
            "table": node.table,
        }

    # --------------------------------------------------------
    # DELETE
    # --------------------------------------------------------

    def execute_delete(self, node: Delete) -> Dict:
        if not self.db.has_collection(node.table):
            raise SQLError(
                "Table '" + node.table + "' does not exist"
            )
        collection = self.db.collection(node.table)

        if node.where is None:
            to_delete = collection.all()
        else:
            to_delete = []
            for r in collection.all():
                row = r.to_dict()
                if self.eval_expr(node.where, row):
                    to_delete.append(r)

        for r in to_delete:
            collection.delete(r.id)

        return {
            "deleted": len(to_delete),
            "table": node.table,
        }

    # --------------------------------------------------------
    # CREATE
    # --------------------------------------------------------

    def execute_create_table(self, node: CreateTable) -> Dict:
        self.db.collection(node.table)
        return {
            "created": node.table,
            "columns": node.columns,
        }

    def execute_create_index(self, node: CreateIndex) -> Dict:
        self.db.collection(node.table).create_index(node.field)
        return {
            "index_created": node.name,
            "table": node.table,
            "field": node.field,
        }

    def execute_drop_table(self, node: DropTable) -> Dict:
        self.db.drop_collection(node.table)
        return {"dropped": node.table}

    def execute_drop_index(self, node: DropIndex) -> Dict:
        # Parse index name "idx_table_field"
        parts = node.name.split("_")
        if len(parts) >= 3:
            self.db.collection(parts[1]).drop_index(parts[2])
        return {"index_dropped": node.name}

    # --------------------------------------------------------
    # Expression Evaluation
    # --------------------------------------------------------

    def eval_expr(self, expr, row) -> Any:
        if isinstance(expr, Literal):
            return expr.value

        if isinstance(expr, Column):
            data = row.get("data", row)
            # Direct field
            if expr.name in data:
                return data[expr.name]
            # Table.field
            if expr.table:
                key = expr.table + "." + expr.name
                if key in row:
                    return row[key]
                # cari di _left atau _right
                if "_left" in row:
                    ldata = row["_left"].get("data", {})
                    if expr.name in ldata:
                        return ldata[expr.name]
                if "_right" in row:
                    rdata = row["_right"].get("data", {})
                    if expr.name in rdata:
                        return rdata[expr.name]
            # Try prefixed keys
            for k in row:
                if k.endswith("." + expr.name):
                    return row[k]
            return None

        if isinstance(expr, BinOp):
            left = self.eval_expr(expr.left, row)
            op = expr.op
            if op == "AND":
                if not self.eval_expr(expr.left, row):
                    return False
                return bool(self.eval_expr(expr.right, row))
            if op == "OR":
                if self.eval_expr(expr.left, row):
                    return True
                return bool(self.eval_expr(expr.right, row))
            right = self.eval_expr(expr.right, row)
            return self._apply_op(left, op, right)

        if isinstance(expr, UnaryOp):
            val = self.eval_expr(expr.expr, row)
            if expr.op == "NOT":
                return not val
            if expr.op == "-":
                return -val if val is not None else None
            return val

        if isinstance(expr, InList):
            val = self.eval_expr(expr.expr, row)
            values = [self.eval_expr(v, row)
                      for v in expr.values]
            result = val in values
            return not result if expr.negate else result

        if isinstance(expr, Like):
            val = self.eval_expr(expr.expr, row)
            pat = self.eval_expr(expr.pattern, row)
            if val is None or pat is None:
                return False
            regex = self._like_to_regex(pat)
            result = bool(re.match(regex, str(val)))
            return not result if expr.negate else result

        if isinstance(expr, Between):
            val = self.eval_expr(expr.expr, row)
            lo = self.eval_expr(expr.low, row)
            hi = self.eval_expr(expr.high, row)
            if val is None or lo is None or hi is None:
                return False
            result = lo <= val <= hi
            return not result if expr.negate else result

        if isinstance(expr, IsNull):
            val = self.eval_expr(expr.expr, row)
            result = val is None
            return not result if expr.negate else result

        if isinstance(expr, FuncCall):
            return self._eval_function(expr, row)

        if isinstance(expr, CaseWhen):
            return self._eval_case(expr, row)

        if isinstance(expr, Coalesce):
            for arg in expr.args:
                v = self.eval_expr(arg, row)
                if v is not None:
                    return v
            return None

        return None

    def _eval_case(self, case, row):
        for cond, result in case.whens:
            if self.eval_expr(cond, row):
                return self.eval_expr(result, row)
        if case.else_result is not None:
            return self.eval_expr(case.else_result, row)
        return None

    def _eval_function(self, func, row):
        """Evaluate scalar function."""
        name = func.name
        args = [self.eval_expr(a, row) for a in func.args]

        if name == "UPPER":
            return str(args[0]).upper() if args[0] is not None else None
        if name == "LOWER":
            return str(args[0]).lower() if args[0] is not None else None
        if name == "LENGTH":
            return len(str(args[0])) if args[0] is not None else 0
        if name == "SUBSTR":
            if not args or args[0] is None:
                return None
            s = str(args[0])
            start = int(args[1]) if len(args) > 1 else 0
            length = int(args[2]) if len(args) > 2 else len(s)
            return s[start:start + length]
        if name == "CONCAT":
            return "".join(str(a) for a in args if a is not None)
        if name == "TRIM":
            return str(args[0]).strip() if args[0] is not None else None
        if name == "REPLACE":
            if len(args) < 3:
                return args[0] if args else None
            return str(args[0]).replace(str(args[1]), str(args[2]))
        if name == "ABS":
            return abs(args[0]) if args and args[0] is not None else None
        if name == "ROUND":
            if not args or args[0] is None:
                return None
            digits = int(args[1]) if len(args) > 1 else 0
            return round(args[0], digits)
        if name == "NOW":
            import time as _t
            return _t.time()
        if name == "DATE":
            import time as _t
            return _t.strftime("%Y-%m-%d")

        # Fallback to aggregate for COUNT, SUM, etc
        return self._eval_aggregate(func, [row])

    def _apply_op(self, left, op, right):
        if op == "=":
            return left == right
        if op in ("!=", "<>"):
            return left != right
        if op == "<":
            return left is not None and right is not None and left < right
        if op == ">":
            return left is not None and right is not None and left > right
        if op == "<=":
            return left is not None and right is not None and left <= right
        if op == ">=":
            return left is not None and right is not None and left >= right
        if op == "+":
            return (left or 0) + (right or 0)
        if op == "-":
            return (left or 0) - (right or 0)
        if op == "*":
            return (left or 0) * (right or 0)
        if op == "/":
            return (left or 0) / (right or 1)
        if op == "%":
            return (left or 0) % (right or 1)
        return None

    @staticmethod
    def _like_to_regex(pattern):
        regex = "^"
        for c in pattern:
            if c == "%":
                regex += ".*"
            elif c == "_":
                regex += "."
            else:
                regex += re.escape(c)
        regex += "$"
        return regex

    # --------------------------------------------------------
    # Aggregation
    # --------------------------------------------------------

    def execute_aggregate(self, node, rows) -> Dict:
        # Group rows
        if node.group_by:
            groups = {}
            for r in rows:
                key = tuple(
                    self.eval_expr(
                        Column(g), r
                    ) for g in node.group_by
                )
                groups.setdefault(key, []).append(r)
        else:
            groups = {None: rows}

        result_rows = []
        for key, group_rows in groups.items():
            out = {}
            # Group by columns
            if node.group_by and key is not None:
                for i, g in enumerate(node.group_by):
                    out[g] = key[i]

            # Aggregate columns
            for c in node.columns:
                if isinstance(c, tuple) and c[0] == "alias":
                    _, expr, alias = c
                    out[alias] = self._eval_aggregate(
                        expr, group_rows
                    )
                elif isinstance(c, FuncCall):
                    out[c.name.lower()] = self._eval_aggregate(
                        c, group_rows
                    )
                elif isinstance(c, Column):
                    out[c.name] = self.eval_expr(
                        c, group_rows[0]
                    )

            # HAVING
            if node.having is not None:
                if not self.eval_expr(node.having, out):
                    continue

            result_rows.append(out)

        # ORDER BY on aggregate
        if node.order_by:
            for col, desc in reversed(node.order_by):
                name = col.name if isinstance(col, Column) else None
                if name:
                    result_rows.sort(
                        key=lambda r: self._sort_key(
                            r.get(name)
                        ),
                        reverse=desc,
                    )

        # LIMIT
        if node.limit is not None:
            result_rows = result_rows[:node.limit]

        return {
            "columns": self._column_names(node.columns),
            "rows": result_rows,
            "count": len(result_rows),
        }

    def _eval_aggregate(self, func, rows) -> Any:
        if not isinstance(func, FuncCall):
            if rows:
                return self.eval_expr(func, rows[0])
            return None

        name = func.name
        args = func.args

        if name == "COUNT":
            if not args or isinstance(args[0], Star):
                return len(rows)
            count = 0
            values = []
            for r in rows:
                v = self.eval_expr(args[0], r)
                if v is not None:
                    values.append(v)
            if func.distinct:
                return len(set(values))
            return len(values)

        if not args:
            return None

        values = []
        for r in rows:
            v = self.eval_expr(args[0], r)
            if v is not None:
                values.append(v)

        if func.distinct:
            values = list(set(values))

        if not values:
            return None

        if name == "SUM":
            return sum(
                v for v in values
                if isinstance(v, (int, float))
            )
        if name == "AVG":
            nums = [
                v for v in values
                if isinstance(v, (int, float))
            ]
            return sum(nums) / len(nums) if nums else None
        if name == "MIN":
            try:
                return min(values)
            except TypeError:
                return None
        if name == "MAX":
            try:
                return max(values)
            except TypeError:
                return None

        return None


__all__ = ["Executor"]
