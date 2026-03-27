"""
Whitespace normalization inside call argument lists using tree-sitter byte spans.

No regular expressions: edits are derived from ``arguments`` node children and
raw UTF-8 slices of the source.
"""

from __future__ import annotations

from typing import Any


def _collect_arguments_nodes(root: Any) -> list[Any]:
    found: list[Any] = []

    def walk(n: Any) -> None:
        if n.type == "arguments":
            found.append(n)
        for c in n.children:
            walk(c)

    walk(root)
    return found


def _is_whitespace_only(b: bytes) -> bool:
    return bool(b) and all(x in b" \t\r\n\f\v" for x in b)


def _edits_for_arguments(node: Any, source: bytes) -> list[tuple[int, int, bytes]]:
    edits: list[tuple[int, int, bytes]] = []
    ch = list(node.children)
    if len(ch) < 2:
        return edits

    if ch[0].type == "(":
        nxt = ch[1]
        if nxt.type != ")" and nxt.type != ",":
            s, e = ch[0].end_byte, nxt.start_byte
            if s < e:
                gap = source[s:e]
                if gap and _is_whitespace_only(gap) and b"\n" not in gap:
                    edits.append((s, e, b""))

    if ch[-1].type == ")":
        prev = ch[-2]
        if prev.type != "(":
            s, e = prev.end_byte, ch[-1].start_byte
            if s < e:
                gap = source[s:e]
                if gap and _is_whitespace_only(gap) and b"\n" not in gap:
                    edits.append((s, e, b""))

    for i, c in enumerate(ch):
        if c.type != ",":
            continue
        prev = ch[i - 1] if i > 0 else None
        nxt = ch[i + 1] if i + 1 < len(ch) else None
        if prev is None or nxt is None:
            continue
        if prev.type == "(" or nxt.type == ")":
            continue

        pe, cb = prev.end_byte, c.start_byte
        ce, nb = c.end_byte, nxt.start_byte

        # Don't remove space before comma when the previous node is also a comma
        # (consecutive empty arguments like `( , , , x)` should keep their spaces).
        if pe < cb and prev.type != ",":
            gap = source[pe:cb]
            if gap:
                if _is_whitespace_only(gap) and b"\n" not in gap:
                    edits.append((pe, cb, b""))
        if ce <= nb:
            if ce < nb:
                gap = source[ce:nb]
                if gap != b" " and b"\n" not in gap:
                    edits.append((ce, nb, b" "))
            else:
                edits.append((ce, ce, b" "))

    return edits


def normalize_argument_list_spacing(source: str, root: Any) -> str:
    """Normalize spaces around commas and padding inside ``( … )`` for every ``arguments`` node."""
    if not source:
        return source
    b = source.encode("utf-8")
    edits: list[tuple[int, int, bytes]] = []
    for args in _collect_arguments_nodes(root):
        edits.extend(_edits_for_arguments(args, b))

    if not edits:
        return source

    edits.sort(key=lambda t: (t[0], t[1]))
    merged: list[tuple[int, int, bytes]] = []
    for s, e, rep in edits:
        if merged and s < merged[-1][1]:
            continue
        merged.append((s, e, rep))

    out = bytearray()
    pos = 0
    for s, e, rep in merged:
        out += b[pos:s]
        out += rep
        pos = e
    out += b[pos:]
    return out.decode("utf-8")


__all__ = ["normalize_argument_list_spacing"]
