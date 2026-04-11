from __future__ import annotations

from typing import Any


def proc_name_span(lines: list[str], proc: Any) -> tuple[int, int]:
    if 0 <= proc.start_idx < len(lines):
        header_line = lines[proc.start_idx]
        try:
            start = header_line.index(proc.name)
            return start, start + len(proc.name)
        except ValueError:
            pass
    start = proc.header_col
    return start, start + len(proc.name)


def proc_param_name_span(header_line: str, param_name: str) -> tuple[int, int] | None:
    open_paren = header_line.find("(")
    close_paren = header_line.rfind(")")
    if open_paren < 0:
        return None
    haystack = header_line[open_paren + 1 : close_paren if close_paren > open_paren else None]
    import re

    m = re.search(rf"\b{re.escape(param_name)}\b", haystack, re.IGNORECASE)
    if not m:
        return None
    start = open_paren + 1 + m.start()
    return start, open_paren + 1 + m.end()


def proc_param_location(
    lines: list[str], proc: Any, param_name: str
) -> tuple[int, int, int] | None:
    scan_idx = proc.start_idx
    paren_depth = 0
    header_started = False
    while 0 <= scan_idx < len(lines):
        line = lines[scan_idx]
        for ch in line:
            if ch == "(":
                paren_depth += 1
                header_started = True
            elif ch == ")":
                paren_depth -= 1
                if header_started and paren_depth <= 0:
                    paren_depth = 0
        import re

        match = re.search(rf"\b{re.escape(param_name)}\b", line, re.IGNORECASE)
        if match:
            return scan_idx, match.start(), match.end()
        if header_started and paren_depth == 0:
            break
        scan_idx += 1
    return None


def proc_by_name_and_line(procs: list[Any], name: str, line_1based: int) -> Any | None:
    line_idx = max(0, line_1based - 1)
    for proc in procs:
        if proc.name.casefold() == name.casefold() and proc.start_idx <= line_idx <= proc.end_idx:
            return proc
    return None


def proc_containing_line(procs: list[Any], line_idx: int) -> Any | None:
    for proc in procs:
        if proc.start_idx <= line_idx <= proc.end_idx:
            return proc
    return None


def procedure_compiler_execution_context(lines: list[str], proc: Any) -> str:
    j = proc.start_idx - 1
    saw_client = False
    saw_server = False
    while j >= 0:
        raw = lines[j]
        if not raw.strip():
            j -= 1
            continue
        if raw.strip().startswith("//"):
            j -= 1
            continue
        s = raw.strip()
        if not s.startswith("&"):
            break
        u = s.casefold().replace(" ", "")
        if "наклиентенасервере" in u:
            return "both"
        if "наклиенте" in u and "насервере" not in u:
            saw_client = True
        elif "насервере" in u and "наклиенте" not in u:
            saw_server = True
        j -= 1
    if saw_client and saw_server:
        return "both"
    if saw_client:
        return "client"
    if saw_server:
        return "server"
    return "none"


def is_typical_client_command_handler(proc: Any, lines: list[str]) -> bool:
    if proc.name.strip().casefold() != "обработкакоманды":
        return False
    ctx = procedure_compiler_execution_context(lines, proc)
    return ctx in ("client", "both", "none")


def is_client_notify_completion_export_handler(proc: Any, lines: list[str]) -> bool:
    if not proc.is_export:
        return False
    ctx = procedure_compiler_execution_context(lines, proc)
    if ctx not in ("client", "both", "none"):
        return False
    n = proc.name.strip().casefold()
    return n.endswith("завершение") or n.endswith("completion")
