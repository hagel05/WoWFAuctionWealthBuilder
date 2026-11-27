"""Read and write the small subset of Lua that WoW addons use for data files.

`to_lua` turns Python data into a Lua table literal (for the WoWFlipData addon).
`parse_saved_variables` reads a SavedVariables file that the game wrote, such as
WTF/Account/<ACCOUNT>/SavedVariables/WoWFlip.lua, back into Python.
"""

from __future__ import annotations

import math
import re

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_KEYWORDS = {
    "and", "break", "do", "else", "elseif", "end", "false", "for", "function", "if", "in",
    "local", "nil", "not", "or", "repeat", "return", "then", "true", "until", "while",
}


def lua_string(s: str) -> str:
    out = ['"']
    for ch in s:
        o = ord(ch)
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif o < 32 or o == 127:
            out.append(f"\\{o:03d}")
        else:
            out.append(ch)
    out.append('"')
    # Lua strings are bytes; the game reads UTF-8, so non-ASCII passes through.
    return "".join(out)


def _key(k) -> str:
    if isinstance(k, bool):
        raise TypeError("boolean table keys are not supported")
    if isinstance(k, int):
        return f"[{k}]"
    if isinstance(k, str):
        return k if _IDENT.match(k) and k not in _KEYWORDS else f"[{lua_string(k)}]"
    raise TypeError(f"unsupported table key {k!r}")


def to_lua(value, indent: int = 0) -> str:
    pad = "\t" * indent
    if value is None:
        return "nil"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return "nil"
        if value.is_integer():
            return str(int(value))
        return repr(round(value, 4))
    if isinstance(value, str):
        return lua_string(value)
    if isinstance(value, (list, tuple)):
        if not value:
            return "{}"
        # Short lists of scalars stay on one line to keep the file small.
        if all(not isinstance(v, (list, tuple, dict)) for v in value):
            return "{" + ", ".join(to_lua(v) for v in value) + "}"
        inner = "".join(f"{pad}\t{to_lua(v, indent + 1)},\n" for v in value)
        return "{\n" + inner + pad + "}"
    if isinstance(value, dict):
        if not value:
            return "{}"
        inner = "".join(
            f"{pad}\t{_key(k)} = {to_lua(v, indent + 1)},\n" for k, v in value.items() if v is not None
        )
        return "{\n" + inner + pad + "}"
    raise TypeError(f"cannot write {type(value).__name__} to Lua")


class LuaParseError(ValueError):
    pass


_TOKEN = re.compile(
    r"""
    (?P<ws>\s+|--\[\[.*?\]\]|--[^\n]*)
  | (?P<str>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')
  | (?P<num>-?(?:0[xX][0-9a-fA-F]+|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?))
  | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op>[{}\[\]=,;])
    """,
    re.VERBOSE | re.DOTALL,
)

_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b", "f": "\f", "v": "\v",
            "\\": "\\", '"': '"', "'": "'", "\n": "\n"}


def _unescape(body: str) -> str:
    i = 0
    data = bytearray()
    while i < len(body):
        ch = body[i]
        if ch != "\\":
            data += ch.encode("utf-8")
            i += 1
            continue
        nxt = body[i + 1] if i + 1 < len(body) else ""
        if nxt.isdigit():
            m = re.match(r"\d{1,3}", body[i + 1:])
            data.append(int(m.group()) & 0xFF)
            i += 1 + len(m.group())
        else:
            data += _ESCAPES.get(nxt, nxt).encode("utf-8")
            i += 2
    return data.decode("utf-8", "replace")


def _tokens(text: str):
    pos = 0
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m:
            raise LuaParseError(f"unexpected character {text[pos]!r} at {pos}")
        pos = m.end()
        kind = m.lastgroup
        if kind == "ws":
            continue
        yield kind, m.group()
    yield "eof", ""


class _Parser:
    def __init__(self, text: str):
        self.toks = list(_tokens(text))
        self.i = 0

    def peek(self):
        return self.toks[self.i]

    def take(self, value: str | None = None):
        tok = self.toks[self.i]
        if value is not None and tok[1] != value:
            raise LuaParseError(f"expected {value!r}, got {tok[1]!r}")
        self.i += 1
        return tok

    def value(self):
        kind, text = self.take()
        if kind == "str":
            return _unescape(text[1:-1])
        if kind == "num":
            if text.lstrip("-").lower().startswith("0x"):
                return int(text, 16)
            f = float(text)
            return int(f) if f.is_integer() and "." not in text and "e" not in text.lower() else f
        if kind == "name" and text in ("true", "false", "nil"):
            return {"true": True, "false": False, "nil": None}[text]
        if text == "{":
            return self.table()
        raise LuaParseError(f"unexpected {text!r}")

    def table(self):
        result: dict = {}
        n = 1
        while self.peek()[1] != "}":
            kind, text = self.peek()
            if text == "[":
                self.take("[")
                key = self.value()
                self.take("]")
                self.take("=")
                val = self.value()
                if val is not None:
                    result[key] = val
            elif kind == "name" and self.toks[self.i + 1][1] == "=":
                self.take()
                self.take("=")
                val = self.value()
                if val is not None:
                    result[text] = val
            else:
                result[n] = self.value()
                n += 1
            if self.peek()[1] in (",", ";"):
                self.take()
        self.take("}")
        return result


def parse_saved_variables(text: str) -> dict:
    """Parse `Name = value` assignments, as the game writes them, into a dict."""
    p = _Parser(text.lstrip("﻿"))
    out = {}
    while p.peek()[0] != "eof":
        kind, name = p.take()
        if kind != "name":
            raise LuaParseError(f"expected a variable name, got {name!r}")
        p.take("=")
        out[name] = p.value()
    return out


def as_list(table) -> list:
    """A Lua array (dict with keys 1..n) as a Python list."""
    if isinstance(table, list):
        return table
    if not isinstance(table, dict):
        return []
    return [table[k] for k in sorted(k for k in table if isinstance(k, int))]
