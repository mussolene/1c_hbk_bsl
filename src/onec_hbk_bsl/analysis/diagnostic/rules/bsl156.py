"""
BSL156 CodeOutOfRegion — BSLLS-oriented checks using line spans for #Область/#Region.

- Module-level ``Перем`` / ``Var`` and executable lines outside procedures must lie
  inside some region pair (stack-matched ``#Область`` … ``#КонецОбласти``).
- Each procedure/function must be fully contained in at least one such region.
- If the module defines no regions but contains procedures or executable module-level
  code, emit a single diagnostic on line 1 (BSLLS ``regions.isEmpty()`` case).

Avoids the synthetic "line 1" diagnostic when all module
content is wrapped by preprocessor blocks, matching BSLLS closer.
"""

from __future__ import annotations

import re

_RE_REGION_OPEN_LINE = re.compile(r"^\s*#(?:Область|Region)\b", re.IGNORECASE)
_RE_REGION_CLOSE_LINE = re.compile(r"^\s*#(?:КонецОбласти|EndRegion)\b", re.IGNORECASE)
_RE_PREPROC_OPEN = re.compile(r"^\s*#(?:Если|If)\b", re.IGNORECASE)
_RE_PREPROC_CLOSE = re.compile(r"^\s*#(?:КонецЕсли|EndIf)\b", re.IGNORECASE)
_RE_COMPILER = re.compile(r"^\s*&\w", re.IGNORECASE)
_RE_MODULE_VAR = re.compile(r"^\s*(?:Перем|Var)\b", re.IGNORECASE)
_RE_RAISE_STMT = re.compile(
    r"^\s*(?:ВызватьИсключение|Raise)\b",
    re.IGNORECASE,
)


def _raw_without_bom(line: str) -> str:
    return line.strip().lstrip("\ufeff")


def module_region_intervals(lines: list[str]) -> list[tuple[int, int]]:
    """Return inclusive (start_line, end_line) for each region block, nesting-correct."""
    stack: list[int] = []
    out: list[tuple[int, int]] = []
    for i, line in enumerate(lines):
        if _RE_REGION_OPEN_LINE.match(line):
            stack.append(i)
        elif _RE_REGION_CLOSE_LINE.match(line):
            if stack:
                s = stack.pop()
                out.append((s, i))
    return out


def line_in_any_region(line_idx: int, intervals: list[tuple[int, int]]) -> bool:
    return any(s <= line_idx <= e for s, e in intervals)


def proc_fully_in_any_region(
    start_idx: int, end_idx: int, intervals: list[tuple[int, int]]
) -> bool:
    return any(s <= start_idx and end_idx <= e for s, e in intervals)


def _strip_line_comment(line: str) -> str:
    if "//" not in line:
        return line
    return line.split("//", 1)[0]


def _is_significant_module_line_raw(line: str) -> bool:
    raw = _raw_without_bom(line)
    if not raw:
        return False
    if raw.startswith("//"):
        return False
    if raw.startswith("#"):
        return False
    if _RE_COMPILER.match(line):
        return False
    return True


def _is_executable_module_statement_line(line: str) -> bool:
    """Module-level statement candidate (not only Перем); excludes raise-only lines."""
    if not _is_significant_module_line_raw(line):
        return False
    code = _strip_line_comment(line).strip()
    if not code:
        return False
    if _RE_MODULE_VAR.match(line):
        return False
    if _RE_RAISE_STMT.match(code):
        return False
    return True


def _line_span_non_ws(line: str) -> tuple[int, int]:
    c0 = len(line) - len(line.lstrip())
    c1 = len(line.rstrip())
    return c0, c1


def _preprocessor_depths(lines: list[str]) -> list[int]:
    depths: list[int] = []
    depth = 0
    for line in lines:
        if _RE_PREPROC_CLOSE.match(line):
            depth = max(0, depth - 1)
        depths.append(depth)
        if _RE_PREPROC_OPEN.match(line):
            depth += 1
    return depths


def bsl156_diagnostics(
    path: str,
    lines: list[str],
    procedures: list[tuple[int, int, str]],
) -> list[tuple[int, int, int, str]]:
    """
    Return (line_1based, char0, char1_exclusive, message) for BSL156.

    *procedures*: ``(start_idx, end_idx, name)`` — same indices as ``_ProcInfo``.
    """
    intervals = module_region_intervals(lines)
    n = len(lines)
    proc_ranges = [(s, e) for s, e, _ in procedures]

    def line_in_proc(i: int) -> bool:
        return any(s <= i <= e for s, e in proc_ranges)

    out: list[tuple[int, int, int, str]] = []
    msg = "Код вне области (#Область / #Region) (BSLLS CodeOutOfRegion)."

    if not intervals:
        first_module_var: tuple[int, int, int] | None = None
        first_module_stmt: tuple[int, int, int] | None = None
        first_proc: tuple[int, int, int] | None = None

        for i, line in enumerate(lines):
            if line_in_proc(i):
                continue
            if not _is_significant_module_line_raw(line):
                continue
            if _RE_MODULE_VAR.match(line) and first_module_var is None:
                c0, c1 = _line_span_non_ws(line)
                first_module_var = (i + 1, c0, c1)
                continue
            if _is_executable_module_statement_line(line) and first_module_stmt is None:
                c0, c1 = _line_span_non_ws(line)
                first_module_stmt = (i + 1, c0, c1)

        for s, _e, _name in procedures:
            if not (0 <= s < n):
                continue
            line = lines[s]
            m = re.search(
                r"(?:Процедура|Procedure|Функция|Function)\s+(\w+)",
                line,
                re.IGNORECASE,
            )
            if m:
                first_proc = (s + 1, m.start(1), m.end(1))
            else:
                c0, c1 = _line_span_non_ws(line)
                first_proc = (s + 1, c0, c1 if c1 > c0 else max(1, len(line)))
            break

        first = first_module_var or first_module_stmt or first_proc
        if first is not None:
            line_1, c0, c1 = first
            out.append((line_1, c0, c1, msg))
        return out

    for s, e, _name in procedures:
        if not proc_fully_in_any_region(s, e, intervals):
            line = lines[s] if 0 <= s < n else ""
            m = re.search(
                r"(?:Процедура|Procedure|Функция|Function)\s+(\w+)",
                line,
                re.IGNORECASE,
            )
            if m:
                c0, c1 = m.start(1), m.end(1)
            else:
                c0, c1 = _line_span_non_ws(line)
                if c1 <= c0:
                    c0, c1 = 0, max(1, len(line))
            out.append((s + 1, c0, c1, msg))

    for i, line in enumerate(lines):
        if line_in_proc(i):
            continue
        if not _is_significant_module_line_raw(line):
            continue
        if _RE_MODULE_VAR.match(line):
            if not line_in_any_region(i, intervals):
                c0, c1 = _line_span_non_ws(line)
                out.append((i + 1, c0, c1, msg))
            continue
        if _is_executable_module_statement_line(line) and not line_in_any_region(i, intervals):
            c0, c1 = _line_span_non_ws(line)
            out.append((i + 1, c0, c1, msg))

    return out
