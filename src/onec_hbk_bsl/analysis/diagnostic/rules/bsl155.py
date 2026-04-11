"""
BSL155 CodeBlockBeforeSub — executable module lines before the first procedure/function.

BSLLS flags a non-empty ``fileCodeBlockBeforeSub`` parse node. We approximate by
skipping blank/comment/preprocessor/compiler-directive lines and module ``Перем``/``Var``
declarations (those belong to module vars, not the «code before sub» block in BSLLS).
"""

from __future__ import annotations

import re

_RE_COMPILER = re.compile(r"^\s*&\w", re.IGNORECASE)
_RE_MODULE_VAR = re.compile(r"^\s*(?:Перем|Var)\b", re.IGNORECASE)


def _raw_without_bom(line: str) -> str:
    return line.strip().lstrip("\ufeff")


def bsl155_code_block_before_sub(
    lines: list[str],
    procedures: list[tuple[int, int]],
) -> list[tuple[int, int, int, str]]:
    """
    Return at most one (line_1based, char0, char1_exclusive, message).

    *procedures*: ``(start_idx, end_idx)`` header line and closing line (``_ProcInfo``).
    """
    if not procedures:
        return []
    first_proc = min(s for s, _e in procedures)
    msg = "Исполняемый код перед объявлениями процедур и функций (BSLLS CodeBlockBeforeSub)."
    for i in range(first_proc):
        line = lines[i]
        raw = _raw_without_bom(line)
        if not raw or raw.startswith("//") or raw.startswith("#"):
            continue
        if _RE_COMPILER.match(line):
            continue
        if _RE_MODULE_VAR.match(line):
            continue
        c0 = len(line) - len(line.lstrip())
        c1 = len(line.rstrip())
        if c1 <= c0:
            c0, c1 = 0, 1
        return [(i + 1, c0, c1, msg)]
    return []
