"""
Character ranges inside BSL double-quoted string literals.

Used to suppress lint diagnostics that overlap string content (including
multi-line literals with ``|`` continuation lines). Line comments ``//`` are
skipped so ``"`` inside a comment does not start a string.
"""

from __future__ import annotations


def double_quoted_string_ranges(content: str) -> list[tuple[int, int]]:
    """
    Return half-open [start, end) character offsets (Unicode code points) in *content*
    that lie inside ``"..."`` literals. ``""`` escapes a single quote inside the literal.
    """
    n = len(content)
    i = 0
    in_string = False
    start = 0
    ranges: list[tuple[int, int]] = []
    in_line_comment = False

    while i < n:
        c = content[i]
        if in_line_comment:
            if c == "\n":
                in_line_comment = False
            i += 1
            continue

        if not in_string:
            if c == "/" and i + 1 < n and content[i + 1] == "/":
                in_line_comment = True
                i += 2
                continue
            if c == '"':
                in_string = True
                start = i
                i += 1
                continue
            i += 1
            continue

        # in_string
        if c == '"':
            if i + 1 < n and content[i + 1] == '"':
                i += 2
                continue
            ranges.append((start, i + 1))
            in_string = False
            i += 1
            continue
        i += 1

    if in_string:
        ranges.append((start, n))

    return ranges


def _line_starts(content: str) -> list[int]:
    """Start offset of each line (0-based line index)."""
    starts = [0]
    for i, c in enumerate(content):
        if c == "\n":
            starts.append(i + 1)
    return starts


def line_col_to_offset(
    content: str,
    line: int,
    col: int,
    *,
    line_starts: list[int] | None = None,
) -> int:
    """0-based *line* and *col* (code units) → absolute offset in *content*.

    Pass *line_starts* from :func:`line_start_offsets` when converting many spans
    for the same *content* — avoids O(n) rescans of the full string per call.
    """
    starts = line_starts if line_starts is not None else _line_starts(content)
    if line >= len(starts):
        return len(content)
    base = starts[line]
    line_end = content.find("\n", base)
    if line_end < 0:
        line_text = content[base:]
    else:
        line_text = content[base:line_end]
    # Clamp column to line length
    col = max(0, min(col, len(line_text)))
    return base + col


def line_start_offsets(content: str) -> list[int]:
    """Start character offset of each line (same as internal line table for *content*)."""
    return _line_starts(content)


def diagnostic_overlaps_string_literal(
    content: str,
    *,
    line: int,
    character: int,
    end_line: int,
    end_character: int,
    ranges: list[tuple[int, int]] | None = None,
    line_starts: list[int] | None = None,
) -> bool:
    """True if the diagnostic span overlaps any double-quoted string range."""
    if not ranges:
        ranges = double_quoted_string_ranges(content)
    if not ranges:
        return False
    ls = line_starts if line_starts is not None else _line_starts(content)
    ds = line_col_to_offset(content, line - 1, character, line_starts=ls)
    de = line_col_to_offset(content, end_line - 1, end_character, line_starts=ls)
    if de < ds:
        de = ds
    for a, b in ranges:
        if ds < b and de > a:
            return True
    return False
