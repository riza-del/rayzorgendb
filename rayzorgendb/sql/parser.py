"""
RayzorgenDB SQL Parser

Parse tokens into AST (Abstract Syntax Tree).
"""

from typing import Any, List, Optional, Dict
from rayzorgendb.sql.lexer import Token, Lexer, SQLError


# ============================================================
# AST Nodes
# ============================================================

class Node:
    pass


class Select(Node):
    def __init__(self):
        self.columns = []          # list of column expressions
        self.table = None
        self.alias = None
        self.where = None
        self.order_by = []         # [(col, desc), ...]
        self.group_by = []         # [col, ...]
        self.having = None
        self.limit = None
        self.offset = 0
        self.joins = []            # list of Join
        self.distinct = False


class Join(Node):
    def __init__(self):
        self.type = "INNER"        # INNER, LEFT, RIGHT
        self.table = None
        self.alias = None
        self.on_left = None
        self.on_right = None


class Insert(Node):
    def __init__(self):
        self.table = None
        self.columns = []
        self.values = []           # list of list


class Update(Node):
    def __init__(self):
        self.table = None
        self.assignments = []      # [(col, value), ...]
        self.where = None


class Delete(Node):
    def __init__(self):
        self.table = None
        self.where = None


class CreateTable(Node):
    def __init__(self):
        self.table = None
        self.columns = []          # [(name, type), ...]


class CreateIndex(Node):
    def __init__(self):
        self.table = None
        self.field = None
        self.name = None


class DropTable(Node):
    def __init__(self):
        self.table = None


class DropIndex(Node):
    def __init__(self):
        self.name = None


# Expressions

class Column(Node):
    def __init__(self, name, table=None):
        self.name = name
        self.table = table


class Star(Node):
    def __init__(self, table=None):
        self.table = table


class Literal(Node):
    def __init__(self, value):
        self.value = value


class BinOp(Node):
    def __init__(self, left, op, right):
        self.left = left
        self.op = op
        self.right = right


class UnaryOp(Node):
    def __init__(self, op, expr):
        self.op = op
        self.expr = expr


class FuncCall(Node):
    def __init__(self, name, args=None, distinct=False):
        self.name = name
        self.args = args or []
        self.distinct = distinct


class InList(Node):
    def __init__(self, expr, values, negate=False):
        self.expr = expr
        self.values = values
        self.negate = negate


class Like(Node):
    def __init__(self, expr, pattern, negate=False):
        self.expr = expr
        self.pattern = pattern
        self.negate = negate


class Between(Node):
    def __init__(self, expr, low, high, negate=False):
        self.expr = expr
        self.low = low
        self.high = high
        self.negate = negate


class IsNull(Node):
    def __init__(self, expr, negate=False):
        self.expr = expr
        self.negate = negate




class CaseWhen(Node):
    def __init__(self):
        self.whens = []      # [(condition, result), ...]
        self.else_result = None


class Coalesce(Node):
    def __init__(self, args):
        self.args = args


class Union(Node):
    def __init__(self):
        self.left = None
        self.right = None
        self.all = False


class Subquery(Node):
    def __init__(self, query):
        self.query = query


# ============================================================
# Parser
# ============================================================

class Parser:
    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> Token:
        return self.tokens[self.pos]

    def next(self) -> Token:
        t = self.tokens[self.pos]
        self.pos += 1
        return t

    def expect(self, type_: str, value: str = None) -> Token:
        t = self.peek()
        if t.type != type_:
            raise SQLError(
                "Expected " + type_ + ", got " + t.type
                + " '" + t.value + "'"
            )
        if value is not None and t.value.upper() != value.upper():
            raise SQLError(
                "Expected '" + value + "', got '" + t.value + "'"
            )
        return self.next()

    def match(self, type_: str, value: str = None) -> bool:
        t = self.peek()
        if t.type != type_:
            return False
        if value is not None and t.value.upper() != value.upper():
            return False
        self.pos += 1
        return True

    def peek_kw(self, *values) -> bool:
        t = self.peek()
        if t.type != "KEYWORD":
            return False
        return t.value.upper() in [v.upper() for v in values]

    # --------------------------------------------------------
    # Entry
    # --------------------------------------------------------

    def parse(self) -> Node:
        t = self.peek()
        if t.type == "KEYWORD":
            kw = t.value.upper()
            if kw == "SELECT":
                return self.parse_select()
            if kw == "INSERT":
                return self.parse_insert()
            if kw == "UPDATE":
                return self.parse_update()
            if kw == "DELETE":
                return self.parse_delete()
            if kw == "CREATE":
                return self.parse_create()
            if kw == "DROP":
                return self.parse_drop()
        raise SQLError("Unknown statement: " + t.value)

    # --------------------------------------------------------
    # SELECT
    # --------------------------------------------------------

    def parse_select(self) -> Select:
        node = Select()
        self.expect("KEYWORD", "SELECT")

        if self.match("KEYWORD", "DISTINCT"):
            node.distinct = True

        # Columns
        node.columns = self.parse_columns()

        # FROM
        if self.match("KEYWORD", "FROM"):
            node.table = self.parse_table_ref()
            # Alias
            if self.peek_kw("AS"):
                self.next()
                alias_t = self.next()
                node.alias = alias_t.value
            elif self.peek().type == "IDENT":
                node.alias = self.next().value

        # JOINs
        while True:
            jtype = self.peek_join_type()
            if jtype is None:
                break
            join = self.parse_join(jtype)
            node.joins.append(join)

        # WHERE
        if self.match("KEYWORD", "WHERE"):
            node.where = self.parse_expr()

        # GROUP BY
        if self.peek_kw("GROUP"):
            self.next()
            self.expect("KEYWORD", "BY")
            node.group_by = self.parse_ident_list()

        # HAVING
        if self.match("KEYWORD", "HAVING"):
            node.having = self.parse_expr()

        # ORDER BY
        if self.peek_kw("ORDER"):
            self.next()
            self.expect("KEYWORD", "BY")
            while True:
                col = self.parse_expr()
                desc = False
                if self.peek_kw("DESC"):
                    self.next()
                    desc = True
                elif self.peek_kw("ASC"):
                    self.next()
                node.order_by.append((col, desc))
                if not self.match("PUNCT", ","):
                    break

        # LIMIT
        if self.match("KEYWORD", "LIMIT"):
            t = self.expect("NUMBER")
            node.limit = int(t.value)

        # OFFSET
        if self.match("KEYWORD", "OFFSET"):
            t = self.expect("NUMBER")
            node.offset = int(t.value)

        return node

    def parse_columns(self):
        cols = []
        while True:
            cols.append(self.parse_select_column())
            if not self.match("PUNCT", ","):
                break
        return cols

    def _is_star(self, t=None):
        if t is None:
            t = self.peek()
        return (t.type in ("PUNCT", "OPERATOR") and
                t.value == "*")

    def parse_select_column(self):
        # Star
        if self._is_star():
            self.next()
            return Star()
        # table.*
        if (self.peek().type == "IDENT" and
                self.pos + 2 < len(self.tokens) and
                self.tokens[self.pos + 1].value == "." and
                self.tokens[self.pos + 2].value == "*"):
            t = self.next()
            self.next()  # dot
            self.next()  # star
            return Star(table=t.value)
        # Expression
        expr = self.parse_expr()
        # Alias
        alias = None
        if self.match("KEYWORD", "AS"):
            alias = self.expect("IDENT").value
        elif self.peek().type == "IDENT":
            alias = self.next().value
        if alias is not None:
            return ("alias", expr, alias)
        return expr

    def parse_table_ref(self):
        t = self.expect("IDENT")
        return t.value

    def peek_join_type(self):
        t = self.peek()
        if t.type != "KEYWORD":
            return None
        if t.value in ("JOIN", "INNER", "LEFT", "RIGHT"):
            return t.value
        return None

    def parse_join(self, jtype) -> Join:
        join = Join()
        if jtype == "INNER":
            join.type = "INNER"
            self.next()
            self.expect("KEYWORD", "JOIN")
        elif jtype in ("LEFT", "RIGHT"):
            join.type = jtype
            self.next()
            self.match("KEYWORD", "OUTER")
            self.expect("KEYWORD", "JOIN")
        else:
            join.type = "INNER"
            self.next()

        join.table = self.parse_table_ref()
        if self.match("KEYWORD", "AS"):
            join.alias = self.expect("IDENT").value
        elif self.peek().type == "IDENT":
            join.alias = self.next().value

        self.expect("KEYWORD", "ON")
        # left = right
        left = self.parse_expr()
        join.on_left = left
        if self.peek().type == "OPERATOR" and self.peek().value == "=":
            self.next()
        else:
            raise SQLError("Expected '=' in JOIN ON")
        join.on_right = self.parse_expr()
        return join

    def parse_ident_list(self):
        cols = []
        while True:
            cols.append(self.expect("IDENT").value)
            if not self.match("PUNCT", ","):
                break
        return cols

    # --------------------------------------------------------
    # INSERT
    # --------------------------------------------------------

    def parse_insert(self) -> Insert:
        node = Insert()
        self.expect("KEYWORD", "INSERT")
        self.expect("KEYWORD", "INTO")
        node.table = self.expect("IDENT").value

        # Columns
        if self.match("PUNCT", "("):
            while True:
                node.columns.append(self.expect("IDENT").value)
                if not self.match("PUNCT", ","):
                    break
            self.expect("PUNCT", ")")

        self.expect("KEYWORD", "VALUES")

        # Values
        while True:
            self.expect("PUNCT", "(")
            row = []
            while True:
                row.append(self.parse_expr())
                if not self.match("PUNCT", ","):
                    break
            self.expect("PUNCT", ")")
            node.values.append(row)
            if not self.match("PUNCT", ","):
                break

        return node

    # --------------------------------------------------------
    # UPDATE
    # --------------------------------------------------------

    def parse_update(self) -> Update:
        node = Update()
        self.expect("KEYWORD", "UPDATE")
        node.table = self.expect("IDENT").value
        self.expect("KEYWORD", "SET")

        while True:
            col = self.expect("IDENT").value
            if not (self.peek().type == "OPERATOR" and
                    self.peek().value == "="):
                raise SQLError("Expected '=' in SET")
            self.next()
            val = self.parse_expr()
            node.assignments.append((col, val))
            if not self.match("PUNCT", ","):
                break

        if self.match("KEYWORD", "WHERE"):
            node.where = self.parse_expr()

        return node

    # --------------------------------------------------------
    # DELETE
    # --------------------------------------------------------

    def parse_delete(self) -> Delete:
        node = Delete()
        self.expect("KEYWORD", "DELETE")
        self.expect("KEYWORD", "FROM")
        node.table = self.expect("IDENT").value
        if self.match("KEYWORD", "WHERE"):
            node.where = self.parse_expr()
        return node

    # --------------------------------------------------------
    # CREATE
    # --------------------------------------------------------

    def parse_create(self) -> Node:
        self.expect("KEYWORD", "CREATE")
        if self.match("KEYWORD", "TABLE"):
            node = CreateTable()
            node.table = self.expect("IDENT").value
            if self.match("PUNCT", "("):
                while True:
                    col = self.expect("IDENT").value
                    typ = self.expect("IDENT").value
                    node.columns.append((col, typ))
                    if not self.match("PUNCT", ","):
                        break
                self.expect("PUNCT", ")")
            return node
        if self.match("KEYWORD", "INDEX"):
            node = CreateIndex()
            node.name = self.expect("IDENT").value
            self.expect("KEYWORD", "ON")
            node.table = self.expect("IDENT").value
            self.expect("PUNCT", "(")
            node.field = self.expect("IDENT").value
            self.expect("PUNCT", ")")
            return node
        raise SQLError("Unknown CREATE")

    def parse_drop(self) -> Node:
        self.expect("KEYWORD", "DROP")
        if self.match("KEYWORD", "TABLE"):
            node = DropTable()
            node.table = self.expect("IDENT").value
            return node
        if self.match("KEYWORD", "INDEX"):
            node = DropIndex()
            node.name = self.expect("IDENT").value
            return node
        raise SQLError("Unknown DROP")

    # --------------------------------------------------------
    # Expressions
    # --------------------------------------------------------

    def parse_expr(self):
        return self.parse_or()

    def parse_or(self):
        left = self.parse_and()
        while self.peek_kw("OR"):
            self.next()
            right = self.parse_and()
            left = BinOp(left, "OR", right)
        return left

    def parse_and(self):
        left = self.parse_not()
        while self.peek_kw("AND"):
            self.next()
            right = self.parse_not()
            left = BinOp(left, "AND", right)
        return left

    def parse_not(self):
        if self.peek_kw("NOT"):
            self.next()
            expr = self.parse_not()
            return UnaryOp("NOT", expr)
        return self.parse_compare()

    def parse_compare(self):
        left = self.parse_add()

        # IS NULL
        if self.peek_kw("IS"):
            self.next()
            negate = self.match("KEYWORD", "NOT")
            self.expect("KEYWORD", "NULL")
            return IsNull(left, negate)

        # IN
        if self.peek_kw("IN"):
            self.next()
            self.expect("PUNCT", "(")
            values = []
            while True:
                values.append(self.parse_expr())
                if not self.match("PUNCT", ","):
                    break
            self.expect("PUNCT", ")")
            return InList(left, values)

        # BETWEEN
        if self.peek_kw("BETWEEN"):
            self.next()
            low = self.parse_add()
            self.expect("KEYWORD", "AND")
            high = self.parse_add()
            return Between(left, low, high)

        # LIKE
        if self.peek_kw("LIKE"):
            self.next()
            pattern = self.parse_add()
            return Like(left, pattern)

        # NOT IN / NOT LIKE / NOT BETWEEN
        if self.peek_kw("NOT"):
            save = self.pos
            self.next()
            if self.peek_kw("IN"):
                self.next()
                self.expect("PUNCT", "(")
                values = []
                while True:
                    values.append(self.parse_expr())
                    if not self.match("PUNCT", ","):
                        break
                self.expect("PUNCT", ")")
                return InList(left, values, negate=True)
            if self.peek_kw("BETWEEN"):
                self.next()
                low = self.parse_add()
                self.expect("KEYWORD", "AND")
                high = self.parse_add()
                return Between(left, low, high, negate=True)
            if self.peek_kw("LIKE"):
                self.next()
                pattern = self.parse_add()
                return Like(left, pattern, negate=True)
            self.pos = save

        # Comparison
        if self.peek().type == "OPERATOR":
            op = self.peek().value
            if op in ("=", "!=", "<>", "<", ">", "<=", ">="):
                self.next()
                right = self.parse_add()
                return BinOp(left, op, right)

        return left

    def parse_add(self):
        left = self.parse_mul()
        while (self.peek().type == "OPERATOR" and
               self.peek().value in ("+", "-")):
            op = self.next().value
            right = self.parse_mul()
            left = BinOp(left, op, right)
        return left

    def parse_mul(self):
        left = self.parse_unary()
        while (self.peek().type == "OPERATOR" and
               self.peek().value in ("*", "/", "%")):
            # Jangan treat * sebagai operator kalau diikuti
            # oleh FROM/VALUES/dll
            nxt = self.peek_after(1)
            if (self.peek().value == "*" and nxt and
                    nxt.type == "KEYWORD" and
                    nxt.value in ("FROM",)):
                break
            op = self.next().value
            right = self.parse_unary()
            left = BinOp(left, op, right)
        return left

    def peek_after(self, n):
        idx = self.pos + n
        if idx < len(self.tokens):
            return self.tokens[idx]
        return None

    def parse_unary(self):
        if (self.peek().type == "OPERATOR" and
                self.peek().value in ("-", "+")):
            op = self.next().value
            return UnaryOp(op, self.parse_unary())
        return self.parse_primary()

    def parse_primary(self):
        t = self.peek()

        # Literals
        if t.type == "NUMBER":
            self.next()
            if "." in t.value:
                return Literal(float(t.value))
            return Literal(int(t.value))

        if t.type == "STRING":
            self.next()
            return Literal(t.value)

        if t.type == "KEYWORD":
            if t.value == "NULL":
                self.next()
                return Literal(None)
            if t.value == "TRUE":
                self.next()
                return Literal(True)
            if t.value == "FALSE":
                self.next()
                return Literal(False)
            if t.value == "CASE":
                return self.parse_case()
            if t.value == "COALESCE":
                return self.parse_coalesce()
            # Aggregates and functions
            if t.value in (
                "COUNT", "SUM", "AVG", "MIN", "MAX",
                "UPPER", "LOWER", "LENGTH", "SUBSTR",
                "CONCAT", "TRIM", "REPLACE", "ABS",
                "ROUND", "CAST", "NOW", "DATE",
            ):
                return self.parse_function()

        if t.type == "IDENT":
            # Function call?
            if (self.pos + 1 < len(self.tokens) and
                    self.tokens[self.pos + 1].value == "("):
                return self.parse_function()
            # Column
            name = self.next().value
            table = None
            if (self.peek().type == "PUNCT" and
                    self.peek().value == "."):
                self.next()  # dot
                table = name
                name = self.expect("IDENT").value
            return Column(name, table)

        # Parens
        if t.type == "PUNCT" and t.value == "(":
            self.next()
            expr = self.parse_expr()
            self.expect("PUNCT", ")")
            return expr

        # Star (fallback)
        if self._is_star():
            self.next()
            return Star()

        raise SQLError("Unexpected token: " + t.value)


    def parse_case(self):
        """Parse CASE WHEN ... THEN ... ELSE ... END"""
        self.expect("KEYWORD", "CASE")
        node = CaseWhen()
        while self.peek_kw("WHEN"):
            self.next()
            cond = self.parse_expr()
            self.expect("KEYWORD", "THEN")
            result = self.parse_expr()
            node.whens.append((cond, result))
        if self.peek_kw("ELSE"):
            self.next()
            node.else_result = self.parse_expr()
        self.expect("KEYWORD", "END")
        return node

    def parse_coalesce(self):
        self.expect("KEYWORD", "COALESCE")
        self.expect("PUNCT", "(")
        args = []
        while True:
            args.append(self.parse_expr())
            if not self.match("PUNCT", ","):
                break
        self.expect("PUNCT", ")")
        return Coalesce(args)

    def parse_function(self):
        name = self.next().value.upper()
        distinct = self.match("KEYWORD", "DISTINCT")
        self.expect("PUNCT", "(")
        args = []
        if self._is_star():
            self.next()
            args.append(Star())
        else:
            while True:
                args.append(self.parse_expr())
                if not self.match("PUNCT", ","):
                    break
        self.expect("PUNCT", ")")
        return FuncCall(name, args, distinct)


def parse(sql: str):
    tokens = Lexer(sql).tokenize()
    return Parser(tokens).parse()


__all__ = ["Parser", "parse", "SQLError"]
