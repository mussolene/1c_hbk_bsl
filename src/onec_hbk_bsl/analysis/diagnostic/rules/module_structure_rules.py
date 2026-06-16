"""
Module-structure rules: async continuation, code before subroutines, code outside regions.
"""

from __future__ import annotations

import re
from functools import lru_cache
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
_BSL154_ASYNC_NAMES = frozenset(x.casefold() for x in _BSL154_ASYNC_PIPE.split("|") if x.strip())
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
_CANONICAL_MODULE_FILE_NAMES_CF = frozenset(
    name.casefold() for name in _CANONICAL_MODULE_FILE_NAMES
)
_ROOT_MODULE_FILES = frozenset(
    {
        "managedapplicationmodule.bsl",
        "ordinaryapplicationmodule.bsl",
        "sessionmodule.bsl",
        "externalconnectionmodule.bsl",
    }
)
_OBJECT_MODULE_FILES = frozenset(
    {
        "objectmodule.bsl",
        "managermodule.bsl",
        "recordsetmodule.bsl",
        "valuemanagermodule.bsl",
        "botmodule.bsl",
    }
)
_MODULE_TYPE_FOLDERS = frozenset(
    {
        "commonmodules",
        "общиемодули",
        "httpservices",
        "httpсервисы",
        "webservices",
        "webсервисы",
        "integrationservices",
        "сервисыинтеграции",
    }
)
_FORM_FOLDERS = frozenset({"forms", "формы"})
_COMMAND_FOLDERS = frozenset({"commands", "команды"})
_EXT_FOLDERS = frozenset({"ext"})


@lru_cache(maxsize=32_768)
def _casefolded_sibling_names(parent: str) -> frozenset[str]:
    try:
        return frozenset(sibling.name.casefold() for sibling in Path(parent).iterdir())
    except OSError:
        return frozenset()


def path_matches_bsl154_module_types(path: str) -> bool:
    low = path.replace("\\", "/").lower()
    if low.endswith("commandmodule.bsl"):
        return True
    if low.endswith("managedapplicationmodule.bsl"):
        return True
    if "/forms/" in low and low.endswith("/form/module.bsl"):
        return True
    return False


_BSL154_STATEMENT_TYPES = frozenset(
    {
        "assignment_statement",
        "break_statement",
        "call_statement",
        "continue_statement",
        "for_each_statement",
        "for_statement",
        "if_statement",
        "return_statement",
        "rise_error_statement",
        "try_statement",
        "var_statement",
        "while_statement",
    }
)


def _node_text(node: object) -> str:
    text = getattr(node, "text", None)
    if text is None:
        return ""
    return text.decode("utf-8", errors="replace") if isinstance(text, bytes) else str(text)


def _node_children(node: object) -> list[object]:
    return list(getattr(node, "children", []) or [])


def _walk(node: object):
    yield node
    for child in _node_children(node):
        yield from _walk(child)


def _nearest_ancestor(node: object, types: frozenset[str]) -> object | None:
    current = getattr(node, "parent", None)
    while current is not None:
        if getattr(current, "type", None) in types:
            return current
        current = getattr(current, "parent", None)
    return None


def _bsl154_method_name(method_call: object) -> str:
    for child in _node_children(method_call):
        if getattr(child, "type", None) == "identifier":
            return _node_text(child)
    return ""


def _bsl154_next_statement(statement: object) -> object | None:
    parent = getattr(statement, "parent", None)
    if parent is None:
        return None
    seen_current = False
    for child in _node_children(parent):
        if child == statement:
            seen_current = True
            continue
        if not seen_current:
            continue
        if getattr(child, "type", None) in _BSL154_STATEMENT_TYPES:
            return child
    return None


def _bsl154_has_blocking_followup(statement: object) -> bool:
    current = statement
    while current is not None:
        next_statement = _bsl154_next_statement(current)
        if next_statement is not None:
            return getattr(next_statement, "type", None) not in {
                "return_statement",
                "break_statement",
            }
        current = _nearest_ancestor(current, _BSL154_STATEMENT_TYPES)
    return False


def bsl154_code_after_async_spans_cst(
    path: str,
    tree: object | None,
) -> list[tuple[int, int, int, str]]:
    if not path_matches_bsl154_module_types(path):
        return []
    root = getattr(tree, "root_node", None)
    if root is None:
        return []

    out: list[tuple[int, int, int, str]] = []
    for node in _walk(root):
        if getattr(node, "type", None) != "method_call":
            continue
        method = _bsl154_method_name(node)
        if not method or method.casefold() not in _BSL154_ASYNC_NAMES:
            continue
        if (
            _nearest_ancestor(node, frozenset({"procedure_definition", "function_definition"}))
            is None
        ):
            continue
        statement = _nearest_ancestor(node, _BSL154_STATEMENT_TYPES)
        if statement is None or not _bsl154_has_blocking_followup(statement):
            continue
        start = getattr(node, "start_point", (0, 0))
        out.append((int(start[0]) + 1, int(start[1]), int(start[1]) + len(method), method))
    return out


@lru_cache(maxsize=131_072)
def is_split_module_fragment(path: str) -> bool:
    current = Path(path)
    if current.suffix.lower() != ".bsl":
        return False
    if current.name.casefold() in _CANONICAL_MODULE_FILE_NAMES_CF:
        return False
    sibling_names = _casefolded_sibling_names(str(current.parent))
    return bool(sibling_names & _CANONICAL_MODULE_FILE_NAMES_CF)


def _is_split_module_fragment(path: str) -> bool:
    return is_split_module_fragment(path)


def path_has_known_bsl156_module_type(path: str) -> bool:
    current = Path(path)
    if current.suffix.lower() != ".bsl":
        return False

    parts = [part.casefold() for part in current.parts]
    name = current.name.casefold()
    parent = current.parent.name.casefold()

    if name in _ROOT_MODULE_FILES and parent in _EXT_FOLDERS:
        return True
    if name in _OBJECT_MODULE_FILES and parent in _EXT_FOLDERS:
        return True
    if name == "commandmodule.bsl" and parent in _EXT_FOLDERS:
        return any(part in _COMMAND_FOLDERS for part in parts)
    if name == "module.bsl" and parent == "form":
        return "ext" in parts and any(part in _FORM_FOLDERS for part in parts)
    if name == "module.bsl" and parent in _EXT_FOLDERS:
        return any(part in _MODULE_TYPE_FOLDERS or part in _FORM_FOLDERS for part in parts)
    return False


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
    if not path_has_known_bsl156_module_type(path) or _is_split_module_fragment(path):
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
