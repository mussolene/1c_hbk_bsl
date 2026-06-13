"""
Module-structure rules: async continuation, code before subroutines, code outside regions.
"""

from __future__ import annotations

import re
from pathlib import Path

_BSL154_ASYNC_PIPE = (
    "ПОКАЗАТЬВОПРОС|SHOWQUERYBOX|ПОКАЗАТЬЗНАЧЕНИЕ|SHOWVALUE|"
    "ПОКАЗАТЬПРЕДУПРЕЖДЕНИЕ|SHOWMESSAGEBOX|ПОКАЗАТЬВВОДДАТЫ|SHOWINPUTDATE|"
    "ПОКАЗАТЬВВОДЗНАЧЕНИЯ|SHOWINPUTVALUE|ПОКАЗАТЬВВОДСТРОКИ|SHOWINPUTSTRING|"
    "ПОКАЗАТЬВВОДЧИСЛА|SHOWINPUTNUMBER|НАЧАТЬУСТАНОВКУВНЕШНЕЙКОМПОНЕНТЫ|BEGININSTALLADDIN|"
    "НАЧАТЬУСТАНОВКУРАСШИРЕНИЯРАБОТЫСФАЙЛАМИ|BEGININSTALLFILESYSTEMEXTENSION|"
    "НАЧАТЬУСТАНОВКУРАСШИРЕНИЯРАБОТЫСКРИПТОГРАФИЕЙ|BEGININSTALLCRYPTOEXTENSION|"
    "НАЧАТЬПОДКЛЮЧЕНИЕРАСШИРЕНИЯРАБОТЫСКРИПТОГРАФИЕЙ|BEGINATTACHINGCRYPTOEXTENSION|"
    "НАЧАТЬПОДКЛЮЧЕНИЕРАСШИРЕНИЯРАБОТЫСФАЙЛАМИ|BEGINATTACHINGFILESYSTEMEXTENSION|"
    "НАЧАТЬПОМЕЩЕНИЕФАЙЛА|BEGINPUTFILE|НАЧАТЬКОПИРОВАНИЕФАЙЛА|BEGINCOPYINGFILE|"
    "НАЧАТЬПЕРЕМЕЩЕНИЕФАЙЛА|BEGINMOVINGFILE|НАЧАТЬПОИСКФАЙЛОВ|BEGINFINDINGFILES|"
    "НАЧАТЬУДАЛЕНИЕФАЙЛОВ|BEGINDELETINGFILES|НАЧАТЬСОЗДАНИЕКАТАЛОГА|BEGINCREATINGDIRECTORY|"
    "НАЧАТЬПОЛУЧЕНИЕКАТАЛОГАВРЕМЕННЫХФАЙЛОВ|BEGINGETTINGTEMPFILESDIR|"
    "НАЧАТЬПОЛУЧЕНИЕКАТАЛОГАДОКУМЕНТОВ|BEGINGETTINGDOCUMENTSDIR|"
    "НАЧАТЬПОЛУЧЕНИЕРАБОЧЕГОКАТАЛОГАДАННЫХПОЛЬЗОВАТЕЛЯ|BEGINGETTINGUSERDATAWORKDIR|"
    "НАЧАТЬПОЛУЧЕНИЕФАЙЛОВ|BEGINGETTINGFILES|НАЧАТЬПОМЕЩЕНИЕФАЙЛОВ|BEGINPUTTINGFILES|"
    "НАЧАТЬЗАПРОСРАЗРЕШЕНИЯПОЛЬЗОВАТЕЛЯ|BEGINREQUESTINGUSERPERMISSION|"
    "НАЧАТЬЗАПУСКПРИЛОЖЕНИЯ|BEGINRUNNINGAPPLICATION"
)
_ASYNC_ALT = "|".join(
    re.escape(n)
    for n in sorted(
        {x.strip() for x in _BSL154_ASYNC_PIPE.split("|") if x.strip()},
        key=len,
        reverse=True,
    )
)
_RE_BSL154_ASYNC = re.compile(rf"\b(?:{_ASYNC_ALT})\s*\(", re.IGNORECASE)
_RE_RETURN_OR_BREAK = re.compile(
    r"^\s*(?:Возврат|Return|Прервать|Break)\b",
    re.IGNORECASE,
)
_RE_COMPILER = re.compile(r"^\s*&\w", re.IGNORECASE)
_RE_MODULE_VAR = re.compile(r"^\s*(?:Перем|Var)\b", re.IGNORECASE)
_RE_REGION_OPEN_LINE = re.compile(r"^\s*#(?:Область|Region)\b", re.IGNORECASE)
_RE_REGION_CLOSE_LINE = re.compile(r"^\s*#(?:КонецОбласти|EndRegion)\b", re.IGNORECASE)
_RE_RAISE_STMT = re.compile(r"^\s*(?:ВызватьИсключение|Raise)\b", re.IGNORECASE)
_CANONICAL_MODULE_FILE_NAMES = frozenset(
    {
        "Module.bsl",
        "ObjectModule.bsl",
        "ManagerModule.bsl",
        "CommandModule.bsl",
        "RecordSetModule.bsl",
        "ManagedApplicationModule.bsl",
        "SessionModule.bsl",
        "ExternalConnectionModule.bsl",
        "OrdinaryApplicationModule.bsl",
    }
)


def path_matches_bsl154_module_types(path: str) -> bool:
    low = path.replace("\\", "/").lower()
    if low.endswith("commandmodule.bsl"):
        return True
    if low.endswith("managedapplicationmodule.bsl"):
        return True
    if "/forms/" in low and low.endswith("/form/module.bsl"):
        return True
    return False


def _is_split_module_fragment(path: str) -> bool:
    current = Path(path)
    if current.suffix.lower() != ".bsl":
        return False
    if current.name in _CANONICAL_MODULE_FILE_NAMES:
        return False
    parent = current.parent
    return any((parent / name).is_file() for name in _CANONICAL_MODULE_FILE_NAMES)


def _code_before_line_comment(line: str) -> str:
    if "//" not in line:
        return line
    return line.split("//", 1)[0]


def _first_sig_line_after(
    lines: list[str], start_after: int, body_end_exclusive: int
) -> tuple[int, str] | None:
    j = start_after
    while j < body_end_exclusive and j < len(lines):
        raw = lines[j]
        s = _code_before_line_comment(raw).strip()
        if not s:
            j += 1
            continue
        if s.startswith("#"):
            j += 1
            continue
        return j, raw
    return None


def _has_blocking_followup(lines: list[str], async_line: int, proc_end_idx: int) -> bool:
    first = _first_sig_line_after(lines, async_line + 1, proc_end_idx)
    if first is None:
        return False
    _li, raw = first
    stmt = _code_before_line_comment(raw).strip()
    if _RE_RETURN_OR_BREAK.match(stmt):
        return False
    return True


def bsl154_code_after_async_spans(
    path: str,
    lines: list[str],
    procedures: list[tuple[int, int]],
) -> list[tuple[int, int, int, str]]:
    if not path_matches_bsl154_module_types(path):
        return []
    out: list[tuple[int, int, int, str]] = []
    for start_idx, end_idx in procedures:
        body_start = start_idx + 1
        body_end_excl = end_idx
        if body_end_excl <= body_start:
            continue
        for li in range(body_start, body_end_excl):
            code_part = _code_before_line_comment(lines[li])
            for m in _RE_BSL154_ASYNC.finditer(code_part):
                raw_m = m.group(0)
                method = raw_m[:-1].strip() if raw_m.endswith("(") else raw_m.strip()
                if not _has_blocking_followup(lines, li, end_idx):
                    continue
                c1 = m.start() + len(method)
                out.append((li + 1, m.start(), c1, method))
    return out


def _raw_without_bom(line: str) -> str:
    return line.strip().lstrip("\ufeff")


def module_region_intervals(lines: list[str]) -> list[tuple[int, int]]:
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


def bsl156_diagnostics(
    path: str,
    lines: list[str],
    procedures: list[tuple[int, int, str]],
) -> list[tuple[int, int, int, str]]:
    if _is_split_module_fragment(path):
        return []

    intervals = module_region_intervals(lines)
    n = len(lines)
    proc_ranges = [(s, e) for s, e, _ in procedures]
    inside_proc = [False] * n
    for s, e in proc_ranges:
        start = max(0, s)
        end = min(n - 1, e)
        for idx in range(start, end + 1):
            inside_proc[idx] = True

    inside_region = [False] * n
    for s, e in intervals:
        start = max(0, s)
        end = min(n - 1, e)
        for idx in range(start, end + 1):
            inside_region[idx] = True

    out: list[tuple[int, int, int, str]] = []
    msg = "Переместите код в область"

    if not intervals:
        first_module_var: tuple[int, int, int] | None = None
        first_module_stmt: tuple[int, int, int] | None = None
        first_proc: tuple[int, int, int] | None = None

        for i, line in enumerate(lines):
            if inside_proc[i]:
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
        if inside_proc[i]:
            continue
        if not _is_significant_module_line_raw(line):
            continue
        if _RE_MODULE_VAR.match(line):
            if not inside_region[i]:
                c0, c1 = _line_span_non_ws(line)
                out.append((i + 1, c0, c1, msg))
            continue
        if _is_executable_module_statement_line(line) and not inside_region[i]:
            c0, c1 = _line_span_non_ws(line)
            out.append((i + 1, c0, c1, msg))

    return out
