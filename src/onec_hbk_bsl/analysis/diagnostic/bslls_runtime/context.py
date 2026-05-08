from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from functools import cached_property
from typing import Any


@dataclass(frozen=True)
class BsllsDocumentContext:
    """Small BSLLS-style document facade over the current parser snapshot."""

    path: str
    content: str
    lines: list[str]
    tree: Any
    snapshot: Any | None = None
    max_bool_ops: int = 3
    bsl036_enabled: bool = False

    @cached_property
    def line_offsets(self) -> list[int]:
        offsets = [0]
        for pos, char in enumerate(self.content):
            if char == "\n":
                offsets.append(pos + 1)
        return offsets

    def to_line_col(self, offset: int) -> tuple[int, int]:
        offsets = self.line_offsets
        line = bisect_right(offsets, offset) - 1
        return line, offset - offsets[line]
