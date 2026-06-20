"""Source text position helpers."""

from __future__ import annotations


def line_start_offsets(content: str) -> list[int]:
    """Start character offset of each line in *content*."""
    starts = [0]
    for idx, char in enumerate(content):
        if char == "\n":
            starts.append(idx + 1)
    return starts


def line_col_to_offset(
    content: str,
    line: int,
    col: int,
    *,
    line_starts: list[int] | None = None,
) -> int:
    """0-based *line* and *col* -> absolute character offset in *content*."""
    starts = line_starts if line_starts is not None else line_start_offsets(content)
    if line >= len(starts):
        return len(content)
    base = starts[line]
    line_end = starts[line + 1] - 1 if line + 1 < len(starts) else len(content)
    return base + max(0, min(col, line_end - base))
