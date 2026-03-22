"""
Split BSL source fragments on commas outside string literals.

Naive ``split(",")`` breaks when a comma appears inside ``"..."``, e.g. default
``Параметр = ","`` or call arguments ``Ф("a,b")``.
"""

from __future__ import annotations

import re


def strip_leading_val_keywords(fragment: str) -> str:
    """
    Remove one or more leading ``Знач`` / ``Val`` keywords.

    Handles a duplicated keyword (e.g. ``Знач Знач Строка``) so the real parameter
    name is still recovered for signatures and regex-based param lists.
    """
    p = fragment.strip()
    while True:
        nxt = re.sub(r"^(?:Знач|Val)\s+", "", p, flags=re.IGNORECASE).strip()
        if nxt == p:
            return p
        p = nxt


def parameter_name_from_declaration_fragment(param_chunk: str) -> str:
    """
    First identifier from a single parameter declaration fragment.

    Strips optional ``&``, ``Знач``/``Val``, and default value after ``=``.
    Used for signatures, inlay hints, and symbol display — not for AST (tree-sitter
    already exposes ``identifier`` nodes).
    """
    p = param_chunk.strip()
    if not p:
        return ""
    p = p.lstrip("&").strip()
    p = strip_leading_val_keywords(p)
    p = p.split("=", 1)[0].strip()
    parts = p.split()
    return parts[0] if parts else ""


def split_commas_outside_double_quotes(segment: str) -> list[str]:
    """
    Split *segment* on commas that are not inside double-quoted literals.

    Doubled quotes ``""`` inside a string (1C escape for a single ``"``) are
    kept inside the literal — they do not end the string.
    """
    segment = segment.strip()
    if not segment:
        return []
    parts: list[str] = []
    buf: list[str] = []
    in_string = False
    i = 0
    n = len(segment)
    while i < n:
        c = segment[i]
        if in_string:
            if c == '"' and i + 1 < n and segment[i + 1] == '"':
                buf.append('""')
                i += 2
                continue
            if c == '"':
                in_string = False
            buf.append(c)
            i += 1
            continue
        if c == '"':
            in_string = True
            buf.append(c)
            i += 1
            continue
        if c == ",":
            piece = "".join(buf).strip()
            if piece:
                parts.append(piece)
            buf = []
            i += 1
            continue
        buf.append(c)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


__all__ = [
    "parameter_name_from_declaration_fragment",
    "split_commas_outside_double_quotes",
    "strip_leading_val_keywords",
]
