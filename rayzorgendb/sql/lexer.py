"""
RayzorgenDB SQL Lexer

Tokenize SQL string into tokens.
"""

import re
from typing import List, NamedTuple


class Token(NamedTuple):
    type: str
    value: str
    pos: int


# SQL Keywords
KEYWORDS = {
    "SELECT", "FROM", "WHERE", "INSERT", "INTO",
    "VALUES", "UPDATE", "SET", "DELETE", "CREATE",
    "DROP", "TABLE", "INDEX", "AND", "OR", "NOT",
    "ORDER", "BY", "ASC", "DESC", "LIMIT", "OFFSET",
    "GROUP", "HAVING", "JOIN", "LEFT", "RIGHT",
    "INNER", "OUTER", "ON", "AS", "IN", "LIKE",
    "BETWEEN", "IS", "NULL", "TRUE", "FALSE",
    "COUNT", "SUM", "AVG", "MIN", "MAX", "DISTINCT",
    "PRIMARY", "KEY",
    # Advanced SQL
    "CASE", "WHEN", "THEN", "ELSE", "END",
    "COALESCE",
    # String functions
    "UPPER", "LOWER", "LENGTH", "SUBSTR",
    "CONCAT", "TRIM", "REPLACE",
    # Math
    "ABS", "ROUND",
    # Date/Time
    "NOW", "DATE",
    # Cast
    "CAST",
    # Union
    "UNION", "ALL",
    "EXPLAIN", "ANALYZE",
}


class SQLError(Exception):
    pass


class Lexer:
    """SQL string to tokens."""

    TOKEN_PATTERNS = [
        ("COMMENT", r"--[^\n]*"),
        ("WHITESPACE", r"\s+"),
        ("STRING", r"'([^'\\]|\\.)*'"),
        ("STRING2", r'"([^"\\]|\\.)*"'),
        ("NUMBER", r"-?\d+\.\d+|-?\d+"),
        ("OPERATOR", r"<=|>=|<>|!=|=|<|>|\+|-|\*|/|%"),
        ("PUNCT", r"[(),;.*]"),
        ("IDENT", r"[A-Za-z_][A-Za-z0-9_]*"),
    ]

    def __init__(self, text: str):
        self.text = text
        self.pos = 0
        self.tokens = []

    def tokenize(self) -> List[Token]:
        self.tokens = []
        self.pos = 0

        while self.pos < len(self.text):
            matched = False
            for tname, pattern in self.TOKEN_PATTERNS:
                m = re.match(pattern, self.text[self.pos:])
                if not m:
                    continue
                value = m.group(0)
                if tname == "WHITESPACE":
                    self.pos += len(value)
                    matched = True
                    break
                if tname == "COMMENT":
                    self.pos += len(value)
                    matched = True
                    break
                if tname == "STRING":
                    # Remove quotes, handle escape
                    val = value[1:-1].replace("\\'", "'")
                    self.tokens.append(Token("STRING", val, self.pos))
                elif tname == "STRING2":
                    val = value[1:-1].replace('\\"', '"')
                    self.tokens.append(Token("STRING", val, self.pos))
                elif tname == "NUMBER":
                    self.tokens.append(Token("NUMBER", value, self.pos))
                elif tname == "IDENT":
                    upper = value.upper()
                    if upper in KEYWORDS:
                        self.tokens.append(Token("KEYWORD", upper, self.pos))
                    else:
                        self.tokens.append(Token("IDENT", value, self.pos))
                else:
                    self.tokens.append(Token(tname, value, self.pos))
                self.pos += len(value)
                matched = True
                break

            if not matched:
                raise SQLError(
                    "Unexpected character at " + str(self.pos)
                    + ": " + repr(self.text[self.pos])
                )

        self.tokens.append(Token("EOF", "", self.pos))
        return self.tokens


def tokenize(sql: str) -> List[Token]:
    return Lexer(sql).tokenize()


__all__ = ["Lexer", "Token", "tokenize", "SQLError"]
