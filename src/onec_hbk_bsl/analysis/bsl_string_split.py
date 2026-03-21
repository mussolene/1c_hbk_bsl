"""
Split BSL source fragments on commas outside string literals.

Naive ``split(",")`` breaks when a comma appears inside ``"..."``, e.g. default
``Параметр = ","`` or call arguments ``Ф("a,b")``.
"""

from __future__ import annotations


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
