"""Shared parsed document snapshot for diagnostics, formatting, and indexing.

The project historically re-parsed the same document and re-walked the same
tree-sitter CST in several layers: diagnostics, formatter, symbol extraction,
call graph extraction, and LSP helpers. This module provides a single lazily
derived snapshot object so those layers can share one parsed view of a file.
"""

from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from onec_hbk_bsl.analysis.bsl_string_split import (
    split_commas_outside_double_quotes,
    strip_leading_val_keywords,
)
from onec_hbk_bsl.analysis.call_graph import Call
from onec_hbk_bsl.analysis.diagnostic.string_state import (
    build_line_string_states,
    comment_start_outside_double_quotes,
    mask_double_quoted_strings_preserve_len,
    strip_inline_comment_preserve_strings,
)
from onec_hbk_bsl.analysis.parse_tree import tree_has_errors
from onec_hbk_bsl.analysis.semantic import SemanticModel, extract_semantic_model
from onec_hbk_bsl.analysis.symbols import Symbol
from onec_hbk_bsl.parser.bsl_parser import BslParser

_RE_PROC_HEADER = re.compile(
    r"^(?P<indent>[ \t]*)(?:(?:Асинх|Async)\s+)?(?P<kw>Процедура|Procedure|Функция|Function)\s+"
    r"(?P<name>\w+)\s*\((?P<params>[^)]*)\)\s*(?P<export>Экспорт|Export)?",
    re.IGNORECASE | re.MULTILINE,
)
_RE_END_PROC = re.compile(
    r"^\s*(?:КонецПроцедуры|EndProcedure|КонецФункции|EndFunction)\s*(?://.*)?$",
    re.IGNORECASE | re.MULTILINE,
)
_RE_REGION_OPEN = re.compile(
    r"^\s*#(?:Область|Region)\s+(?P<name>.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_RE_REGION_CLOSE = re.compile(
    r"^\s*#(?:КонецОбласти|EndRegion)\b.*$",
    re.IGNORECASE | re.MULTILINE,
)
_RE_QUERY_TEXT_START = re.compile(r'"\s*(?:ВЫБРАТЬ|SELECT)\b', re.IGNORECASE)
_RE_QUERY_INLINE_COMMENT = re.compile(r"\s*//.*$")
_CC_OPEN = re.compile(
    r"^\s*(?:Если|If|ДляКаждого|ForEach|Для|For|Пока|While|Исключение|Except)\b",
    re.IGNORECASE,
)
_CC_CLOSE = re.compile(
    r"^\s*(?:КонецЕсли|EndIf|КонецЦикла|EndDo|КонецПопытки|EndTry)\b",
    re.IGNORECASE,
)
_CC_ELSE = re.compile(
    r"^\s*(?:ИначеЕсли|ElsIf|Иначе|Else)\b",
    re.IGNORECASE,
)
_RE_MCCABE_BRANCH = re.compile(
    r"^\s*(?:Если|If|ИначеЕсли|ElsIf|Иначе|Else|Для|For|ДляКаждого|ForEach|Пока|While|Исключение|Except|Перейти|Goto)\b",
    re.IGNORECASE,
)
_RE_MCCABE_BOOL = re.compile(r"\b(?:И|And|ИЛИ|Or)\b", re.IGNORECASE)
_RE_MCCABE_TERNARY = re.compile(r"\?\s*\(")
_RE_MCCABE_CALL_PREFIX = re.compile(
    r"(?P<name>[A-Za-zА-Яа-яЁё_]\w*)\s*$",
    re.IGNORECASE | re.UNICODE,
)
_RE_COGNITIVE_BOOL_TOKEN = re.compile(
    r"\?\s*\(|\b(?:Не|Not|И|And|ИЛИ|Or)\b|[()]",
    re.IGNORECASE,
)
_RE_COGNITIVE_BOOL_START = re.compile(r"^\s*(?:И|And|ИЛИ|Or)\b", re.IGNORECASE)
_RE_COGNITIVE_OPEN_CONTROL_EXPR = re.compile(
    r"\b(?:Если|If|ИначеЕсли|ElsIf|Пока|While)\b",
    re.IGNORECASE,
)
_RE_COGNITIVE_EXPR_TERMINATOR = re.compile(
    r"(?:;|\b(?:Тогда|Then|Цикл|Do)\b)\s*$",
    re.IGNORECASE,
)
_RE_COGNITIVE_CONTROL_TERMINATOR = re.compile(r"\b(?:Тогда|Then|Цикл|Do)\b", re.IGNORECASE)
_RE_ASSIGNMENT_CONTINUATION = re.compile(r"[=+\-*/]\s*$")
_MCCABE_GROUPING_KEYWORDS = frozenset(
    {
        "если",
        "if",
        "иначеесли",
        "elsif",
        "пока",
        "while",
        "не",
        "not",
        "и",
        "and",
        "или",
        "or",
        "возврат",
        "return",
    }
)


def _query_content_end_quote(content: str) -> int | None:
    pos = 0
    while pos < len(content):
        if content[pos] != '"':
            pos += 1
            continue
        if pos + 1 < len(content) and content[pos + 1] == '"':
            pos += 2
            continue
        return pos
    return None


def _is_mccabe_grouping_paren(text: str, index: int) -> bool:
    prefix = text[:index]
    if not prefix.strip():
        return True
    previous = prefix.rstrip()
    previous_char = previous[-1]
    if previous_char == "?":
        return False
    match = _RE_MCCABE_CALL_PREFIX.search(previous)
    if match is None:
        return True
    return match.group("name").casefold() in _MCCABE_GROUPING_KEYWORDS


def _count_mccabe_bool_ops(text: str, paren_depth: int = 0) -> tuple[int, int]:
    paren_stack = [True] * max(0, paren_depth)
    if _RE_MCCABE_BOOL.search(text) is None:
        if "(" not in text and ")" not in text:
            return 0, paren_depth
        for i, ch in enumerate(text):
            if ch == "(":
                paren_stack.append(_is_mccabe_grouping_paren(text, i))
            elif ch == ")" and paren_stack:
                paren_stack.pop()
        return 0, sum(1 for item in paren_stack if item)
    count = 0
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "(":
            paren_stack.append(_is_mccabe_grouping_paren(text, i))
            i += 1
            continue
        if ch == ")":
            if paren_stack:
                paren_stack.pop()
            i += 1
            continue
        match = _RE_MCCABE_BOOL.match(text, i)
        if match:
            count += 1 + sum(1 for item in paren_stack if item)
            i = match.end()
            continue
        i += 1
    return count, sum(1 for item in paren_stack if item)


def _count_cognitive_ternary_ops(
    text: str,
    control_nesting: int,
    paren_stack: list[bool],
) -> int:
    score = 0
    i = 0
    while i < len(text):
        if text[i] == "?":
            j = i + 1
            while j < len(text) and text[j].isspace():
                j += 1
            if j >= len(text) or text[j] != "(":
                i += 1
                continue
            ternary_depth = sum(1 for item in paren_stack if item)
            score += 1 + control_nesting + ternary_depth
            paren_stack.append(True)
            i = j + 1
            continue
        if text[i] == "(":
            paren_stack.append(False)
        elif text[i] == ")" and paren_stack:
            paren_stack.pop()
        i += 1
    return score


def _count_cognitive_bool_ops(text: str, last_op: str | None = None) -> tuple[int, str | None]:
    count = 0
    current = last_op
    reset_on_close: list[bool] = []
    pending_not = False
    bool_seen_on_line = False
    for match in _RE_COGNITIVE_BOOL_TOKEN.finditer(text):
        lexeme = match.group(0)
        folded = lexeme.casefold()
        if lexeme.startswith("?"):
            if not bool_seen_on_line:
                current = None
            pending_not = False
            continue
        if lexeme == "(":
            is_not_grouping = pending_not and _is_mccabe_grouping_paren(text, match.start())
            if is_not_grouping:
                current = None
            reset_on_close.append(is_not_grouping)
            pending_not = False
            continue
        if lexeme == ")":
            if reset_on_close and reset_on_close.pop():
                current = None
            pending_not = False
            continue
        if folded in {"не", "not"}:
            pending_not = True
            continue
        pending_not = False
        op = "and" if folded in {"and", "и"} else "or"
        if op != current:
            count += 1
            current = op
        bool_seen_on_line = True
    return count, current


def _line_has_self_call(line: str, proc_name: str | None) -> bool:
    if not proc_name:
        return False
    return bool(re.search(rf"(?<![.\w]){re.escape(proc_name)}\s*\(", line, re.IGNORECASE))


def _calc_complexity_metrics_from_lines(
    lines: list[str],
    start_idx: int,
    end_idx: int,
    *,
    masked_lines: list[str],
    proc_name: str | None = None,
) -> tuple[int, int]:
    cognitive = 0
    nesting = 0
    bool_last_op: str | None = None
    bool_expr_open = False
    ternary_paren_stack: list[bool] = []
    mccabe = 1
    paren_depth = 0
    for i in range(start_idx + 1, min(end_idx, len(lines))):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("//"):
            continue
        if line.lstrip().startswith("|"):
            bool_last_op = None
            bool_expr_open = False
            ternary_paren_stack.clear()
            paren_depth = 0
            continue
        line_no_strings = masked_lines[i]

        starts_with_bool = bool(_RE_COGNITIVE_BOOL_START.match(line_no_strings))
        line_bool_count, bool_last_op = _count_cognitive_bool_ops(
            line_no_strings,
            bool_last_op if (bool_expr_open or starts_with_bool) else None,
        )
        cognitive += line_bool_count
        line_has_bool = line_bool_count > 0 or _RE_MCCABE_BOOL.search(line_no_strings) is not None
        opens_control_expr = bool(
            _RE_COGNITIVE_OPEN_CONTROL_EXPR.search(line_no_strings)
            and not _RE_COGNITIVE_CONTROL_TERMINATOR.search(line_no_strings)
        )
        line_terminates_expr = bool(_RE_COGNITIVE_EXPR_TERMINATOR.search(line_no_strings))
        bool_expr_open = (
            opens_control_expr
            or bool(_RE_ASSIGNMENT_CONTINUATION.search(line_no_strings))
            or (line_has_bool and not line_terminates_expr)
            or bool((bool_expr_open or starts_with_bool) and not line_terminates_expr)
        )
        if not bool_expr_open:
            bool_last_op = None
        ternary_count = len(_RE_MCCABE_TERNARY.findall(line_no_strings))
        cognitive += _count_cognitive_ternary_ops(
            line_no_strings,
            nesting,
            ternary_paren_stack,
        )
        has_self_call = _line_has_self_call(line_no_strings, proc_name)
        if has_self_call:
            cognitive += 1
        if _CC_OPEN.match(line):
            cognitive += 1 + nesting
            nesting += 1
        elif _CC_CLOSE.match(line):
            nesting = max(0, nesting - 1)
        elif _CC_ELSE.match(line):
            cognitive += 1

        if _RE_MCCABE_BRANCH.match(line_no_strings):
            mccabe += 1
        bool_count, paren_depth = _count_mccabe_bool_ops(line_no_strings, paren_depth)
        mccabe += bool_count
        mccabe += ternary_count
        if has_self_call:
            mccabe += 1
    return cognitive, mccabe


@dataclass(frozen=True)
class ProcInfo:
    """Procedure or function definition extracted from source."""

    name: str
    kind: str
    start_idx: int
    end_idx: int
    is_export: bool
    params: list[str]
    val_params: list[str]
    optional_count: int
    header_col: int = 0
    optional_params: frozenset[str] = frozenset()


@dataclass(frozen=True)
class RegionInfo:
    """#Область / #Region block in the source."""

    name: str
    start_idx: int
    end_idx: int


@dataclass(frozen=True)
class QueryTextLineInfo:
    """One logical content line inside an embedded query string block."""

    line_no: int
    content_base: int
    content: str
    head: str
    ended_query: bool


@dataclass(frozen=True)
class QueryTextBlockInfo:
    """Embedded query string block with pre-split logical lines."""

    start_idx: int
    block_lines: tuple[str, ...]
    content_lines: tuple[QueryTextLineInfo, ...]

    @property
    def query_text(self) -> str:
        return "\n".join(self.block_lines)

    @property
    def head_text(self) -> str:
        return "\n".join(line.head for line in self.content_lines)


def _parse_params(params_str: str) -> list[tuple[str, bool, bool]]:
    result: list[tuple[str, bool, bool]] = []
    for raw in split_commas_outside_double_quotes(params_str):
        raw = raw.strip()
        if not raw:
            continue
        is_val = bool(re.match(r"^(?:Знач|Val)\s+", raw, re.IGNORECASE))
        clean = strip_leading_val_keywords(raw)
        is_optional = "=" in clean
        name = clean.split("=")[0].strip()
        if name and re.match(r"^\w+$", name):
            result.append((name, is_val, is_optional))
    return result


def _ts_node_text(node: Any) -> str:
    text = getattr(node, "text", None)
    if text is None:
        return ""
    return text.decode("utf-8", errors="replace") if isinstance(text, bytes) else str(text)


def _ts_node_to_proc_info(node: Any) -> ProcInfo | None:
    name = ""
    params: list[str] = []
    val_params: list[str] = []
    optional_count = 0
    is_export = False
    optional_params_list: list[str] = []

    for child in getattr(node, "children", []) or []:
        child_type = getattr(child, "type", None)
        if child_type == "identifier" and not name:
            name = _ts_node_text(child)
        elif child_type == "EXPORT_KEYWORD":
            is_export = True
        elif child_type == "parameters":
            for param in getattr(child, "children", []) or []:
                if getattr(param, "type", None) != "parameter":
                    continue
                param_name = ""
                is_val = False
                has_default = False
                for param_child in getattr(param, "children", []) or []:
                    param_child_type = getattr(param_child, "type", None)
                    if param_child_type == "VAL_KEYWORD":
                        is_val = True
                    elif param_child_type == "identifier" and not param_name:
                        param_name = _ts_node_text(param_child)
                    elif param_child_type == "=":
                        has_default = True
                if param_name:
                    params.append(param_name)
                    if is_val:
                        val_params.append(param_name)
                    if has_default:
                        optional_count += 1
                        optional_params_list.append(param_name)

    node_text = _ts_node_text(node)
    header_match = _RE_PROC_HEADER.search(node_text)
    if header_match is not None:
        name = header_match.group("name")
        is_export = bool(header_match.group("export"))
        parsed = _parse_params(header_match.group("params") or "")
        params = [param[0] for param in parsed]
        val_params = [param[0] for param in parsed if param[1]]
        optional_count = sum(1 for param in parsed if param[2])
        optional_params_list = [param[0] for param in parsed if param[2]]

    if not name:
        return None

    kind = "function" if getattr(node, "type", None) == "function_definition" else "procedure"
    return ProcInfo(
        name=name,
        kind=kind,
        start_idx=node.start_point[0],
        end_idx=node.end_point[0],
        is_export=is_export,
        params=params,
        val_params=val_params,
        optional_count=optional_count,
        header_col=node.start_point[1],
        optional_params=frozenset(optional_params_list),
    )


def _collect_procs_from_node(node: Any, result: list[ProcInfo]) -> None:
    if getattr(node, "type", None) in ("procedure_definition", "function_definition"):
        proc = _ts_node_to_proc_info(node)
        if proc:
            result.append(proc)
        return
    for child in getattr(node, "children", []) or []:
        _collect_procs_from_node(child, result)


def _collect_proc_names_from_node(node: Any, result: set[str]) -> None:
    node_type = getattr(node, "type", None)
    if node_type in ("procedure_definition", "function_definition"):
        for child in getattr(node, "children", []) or []:
            if getattr(child, "type", None) == "identifier":
                name = _ts_node_text(child)
                if name:
                    result.add(name.casefold())
                break
        return
    for child in getattr(node, "children", []) or []:
        _collect_proc_names_from_node(child, result)


def _find_procedures_from_tree(tree: Any) -> list[ProcInfo]:
    root = getattr(tree, "root_node", None)
    if root is None or not isinstance(getattr(root, "text", None), (bytes, type(None))):
        return []
    result: list[ProcInfo] = []
    _collect_procs_from_node(root, result)
    return result


def find_procedure_names_from_tree(tree: Any) -> frozenset[str]:
    root = getattr(tree, "root_node", None)
    if root is None or not isinstance(getattr(root, "text", None), (bytes, bytearray)):
        return frozenset()
    result: set[str] = set()
    _collect_proc_names_from_node(root, result)
    return frozenset(result)


def find_procedure_names_in_content(content: str) -> frozenset[str]:
    return frozenset(proc.name.casefold() for proc in _find_procedures(content))


def _line_break_positions(content: str) -> list[int]:
    breaks: list[int] = []
    start = content.find("\n")
    while start != -1:
        breaks.append(start)
        start = content.find("\n", start + 1)
    return breaks


def _line_index_for_offset(line_breaks: list[int], offset: int) -> int:
    return bisect_left(line_breaks, offset)


def _find_procedures(content: str) -> list[ProcInfo]:
    line_breaks = _line_break_positions(content)
    ends = [
        _line_index_for_offset(line_breaks, match.start())
        for match in _RE_END_PROC.finditer(content)
    ]

    result: list[ProcInfo] = []
    for match in _RE_PROC_HEADER.finditer(content):
        start_idx = _line_index_for_offset(line_breaks, match.start())
        kw = match.group("kw").lower()
        name = match.group("name")
        params_str = match.group("params") or ""
        is_export = bool(match.group("export"))
        kind = "function" if kw in ("функция", "function") else "procedure"
        header_col = len(match.group("indent"))

        parsed = _parse_params(params_str)
        params = [param[0] for param in parsed]
        val_params = [param[0] for param in parsed if param[1]]
        optional_count = sum(1 for param in parsed if param[2])
        optional_params = frozenset(param[0] for param in parsed if param[2])

        end_idx = start_idx + 5
        end_pos = bisect_right(ends, start_idx)
        if end_pos < len(ends):
            end_idx = ends[end_pos]

        result.append(
            ProcInfo(
                name=name,
                kind=kind,
                start_idx=start_idx,
                end_idx=end_idx,
                is_export=is_export,
                params=params,
                val_params=val_params,
                optional_count=optional_count,
                header_col=header_col,
                optional_params=optional_params,
            )
        )
    return result


def _find_regions(content: str) -> list[RegionInfo]:
    line_breaks = _line_break_positions(content)
    opens_iter = iter(_RE_REGION_OPEN.finditer(content))
    closes_iter = iter(_RE_REGION_CLOSE.finditer(content))
    next_open = next(opens_iter, None)
    next_close = next(closes_iter, None)
    stack: list[tuple[str, int]] = []
    result: list[RegionInfo] = []

    while next_open is not None or next_close is not None:
        open_pos = next_open.start() if next_open is not None else None
        close_pos = next_close.start() if next_close is not None else None
        use_open = close_pos is None or (open_pos is not None and open_pos <= close_pos)

        if use_open and next_open is not None:
            stack.append(
                (
                    next_open.group("name"),
                    _line_index_for_offset(line_breaks, next_open.start()),
                )
            )
            next_open = next(opens_iter, None)
            continue

        if next_close is not None:
            end_idx = _line_index_for_offset(line_breaks, next_close.start())
            if stack:
                name, start_idx = stack.pop()
                result.append(RegionInfo(name=name, start_idx=start_idx, end_idx=end_idx))
            next_close = next(closes_iter, None)

    # Unclosed regions are retained with a short synthetic span to preserve fallback behavior.
    for name, start_idx in stack:
        result.append(RegionInfo(name=name, start_idx=start_idx, end_idx=start_idx + 1))

    result.sort(key=lambda region: region.start_idx)
    return result


def _find_regions_from_tree(tree: Any) -> list[RegionInfo]:
    root = getattr(tree, "root_node", None)
    if root is None or not isinstance(getattr(root, "text", None), bytes):
        return []

    opens: list[tuple[int, str]] = []
    closes: list[int] = []

    def visit(node: Any) -> None:
        if getattr(node, "type", None) == "preprocessor":
            child_types = {getattr(child, "type", None) for child in getattr(node, "children", [])}
            start_idx = node.start_point[0] if getattr(node, "start_point", None) else 0

            if "PREPROC_REGION_KEYWORD" in child_types:
                region_name = ""
                seen_keyword = False
                for child in getattr(node, "children", []) or []:
                    child_type = getattr(child, "type", None)
                    if child_type == "PREPROC_REGION_KEYWORD":
                        seen_keyword = True
                        continue
                    if seen_keyword and child_type == "identifier":
                        region_name = _ts_node_text(child)
                        break
                opens.append((start_idx, region_name))
                return

            if "PREPROC_ENDREGION_KEYWORD" in child_types:
                closes.append(start_idx)
                return

        for child in getattr(node, "children", []) or []:
            visit(child)

    visit(root)

    events = [(idx, "open", name) for idx, name in opens]
    events.extend((idx, "close", "") for idx in closes)
    events.sort(key=lambda item: (item[0], 0 if item[1] == "open" else 1))
    stack: list[tuple[str, int]] = []
    result: list[RegionInfo] = []
    for idx, kind, name in events:
        if kind == "open":
            stack.append((name, idx))
        elif stack:
            open_name, start_idx = stack.pop()
            result.append(RegionInfo(name=open_name, start_idx=start_idx, end_idx=idx))
    for name, start_idx in stack:
        result.append(RegionInfo(name=name, start_idx=start_idx, end_idx=start_idx + 1))
    result.sort(key=lambda region: region.start_idx)
    return result


def _build_proc_node_map(tree: Any) -> dict[tuple[str, int, str], Any]:
    result: dict[tuple[str, int, str], Any] = {}
    root = getattr(tree, "root_node", None)
    if root is None or not isinstance(getattr(root, "text", None), (bytes, bytearray)):
        return result

    def collect(node: Any) -> None:
        if getattr(node, "type", None) in ("procedure_definition", "function_definition"):
            info = _ts_node_to_proc_info(node)
            if info:
                result[(info.name, info.start_idx, info.kind)] = node
            return
        for child in getattr(node, "children", []) or []:
            collect(child)

    collect(root)
    return result


def _build_query_text_blocks(lines: list[str]) -> list[QueryTextBlockInfo]:
    result: list[QueryTextBlockInfo] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        starts_query = bool(_RE_QUERY_TEXT_START.search(line))
        if not starts_query and '"' in line:
            j_probe = i + 1
            while j_probe < len(lines) and (
                not lines[j_probe].strip() or lines[j_probe].lstrip().startswith("|")
            ):
                if re.match(r"^\s*\|\s*(?:ВЫБРАТЬ|SELECT)\b", lines[j_probe], re.IGNORECASE):
                    starts_query = True
                    break
                j_probe += 1
        if not starts_query:
            i += 1
            continue
        block_lines = [line]
        j = i + 1
        while j < len(lines) and (
            lines[j].lstrip().startswith("|")
            or lines[j].lstrip().startswith("//")
            or not lines[j].strip()
        ):
            block_lines.append(lines[j])
            j += 1

        content_lines: list[QueryTextLineInfo] = []
        for offset, raw_line in enumerate(block_lines):
            stripped = raw_line.rstrip()
            if not stripped:
                continue

            if offset == 0:
                quote_pos = raw_line.find('"')
                if quote_pos < 0:
                    continue
                content_base = quote_pos + 1
                raw_content = raw_line[content_base:]
            else:
                pipe_pos = raw_line.find("|")
                if pipe_pos < 0:
                    continue
                after_pipe = raw_line[pipe_pos + 1 :]
                leading_ws = len(after_pipe) - len(after_pipe.lstrip())
                content_base = pipe_pos + 1 + leading_ws
                raw_content = after_pipe.lstrip()

            content = _RE_QUERY_INLINE_COMMENT.sub("", raw_content).rstrip().lstrip()
            if not content:
                continue

            end_quote = _query_content_end_quote(content)
            ended_query = end_quote is not None
            head = content[:end_quote].rstrip() if ended_query else content
            if not head:
                if ended_query:
                    break
                continue

            content_lines.append(
                QueryTextLineInfo(
                    line_no=i + offset + 1,
                    content_base=content_base,
                    content=content,
                    head=head,
                    ended_query=ended_query,
                )
            )
            if ended_query:
                break

        result.append(
            QueryTextBlockInfo(
                start_idx=i,
                block_lines=tuple(block_lines),
                content_lines=tuple(content_lines),
            )
        )
        i = j
    return result


@dataclass(slots=True)
class DocumentSnapshot:
    """One parsed view of a BSL document with lazily derived analysis data."""

    path: str
    content: str
    tree: Any

    _lines: list[str] | None = None
    _procs: list[ProcInfo] | None = None
    _regions: list[RegionInfo] | None = None
    _proc_node_map: dict[tuple[str, int, str], Any] | None = None
    _symbols: list[Symbol] | None = None
    _calls: list[Call] | None = None
    _semantic_model: SemanticModel | None = None
    _query_blocks: list[QueryTextBlockInfo] | None = None
    _line_string_states: list[bool] | None = None
    _comment_starts: list[int | None] | None = None
    _masked_lines: list[str] | None = None
    _code_lines_wo_comments: list[str] | None = None
    _counter_lines: list[str] | None = None
    _line_lengths: list[int] | None = None
    _blank_line_flags: list[bool] | None = None
    _has_parse_errors: bool | None = None
    _ts_node_groups: dict[str, list[Any]] | None = None
    _complexity_metrics_cache: dict[tuple[tuple[int, int], ...], list[tuple[int, int]]] | None = (
        None
    )
    _runtime_call_context_cache: Any | None = None

    @property
    def root_node(self) -> Any | None:
        return getattr(self.tree, "root_node", None)

    @property
    def lines(self) -> list[str]:
        if self._lines is None:
            self._lines = self.content.splitlines()
        return self._lines

    @property
    def is_tree_sitter(self) -> bool:
        root = self.root_node
        return root is not None and isinstance(getattr(root, "text", None), (bytes, bytearray))

    @property
    def has_parse_errors(self) -> bool:
        if self._has_parse_errors is None:
            root = self.root_node
            if root is None or not self.is_tree_sitter:
                self._has_parse_errors = True
            else:
                self._has_parse_errors = tree_has_errors(root)
        return self._has_parse_errors

    @property
    def tree_ok(self) -> bool:
        return self.is_tree_sitter and not self.has_parse_errors

    @property
    def procedures(self) -> list[ProcInfo]:
        if self._procs is None:
            self._procs = (
                _find_procedures_from_tree(self.tree)
                if self.is_tree_sitter
                else _find_procedures(self.content)
            )
        return self._procs

    @property
    def regions(self) -> list[RegionInfo]:
        if self._regions is None:
            self._regions = (
                _find_regions_from_tree(self.tree)
                if self.is_tree_sitter
                else _find_regions(self.content)
            )
            if not self._regions:
                self._regions = _find_regions(self.content)
        return self._regions

    @property
    def proc_node_map(self) -> dict[tuple[str, int, str], Any]:
        if self._proc_node_map is None:
            self._proc_node_map = _build_proc_node_map(self.tree)
        return self._proc_node_map

    @property
    def symbols(self) -> list[Symbol]:
        if self._symbols is None:
            self._symbols = self.semantic_model.symbols
        return self._symbols

    @property
    def calls(self) -> list[Call]:
        if self._calls is None:
            self._calls = self.semantic_model.calls
        return self._calls

    @property
    def semantic_model(self) -> SemanticModel:
        if self._semantic_model is None:
            self._semantic_model = extract_semantic_model(self.tree, file_path=self.path)
        return self._semantic_model

    @property
    def query_text_blocks(self) -> list[QueryTextBlockInfo]:
        if self._query_blocks is None:
            self._query_blocks = _build_query_text_blocks(self.lines)
        return self._query_blocks

    @property
    def line_string_states(self) -> list[bool]:
        if self._line_string_states is None:
            self._line_string_states = build_line_string_states(self.lines)
        return self._line_string_states

    @property
    def comment_starts(self) -> list[int | None]:
        if self._comment_starts is None:
            states = self.line_string_states
            self._comment_starts = [
                comment_start_outside_double_quotes(line, states[idx])
                for idx, line in enumerate(self.lines)
            ]
        return self._comment_starts

    @property
    def masked_lines(self) -> list[str]:
        if self._masked_lines is None:
            states = self.line_string_states
            self._masked_lines = [
                line if states[idx] else mask_double_quoted_strings_preserve_len(line)
                for idx, line in enumerate(self.lines)
            ]
        return self._masked_lines

    @property
    def code_lines_without_comments(self) -> list[str]:
        if self._code_lines_wo_comments is None:
            self._code_lines_wo_comments = [
                strip_inline_comment_preserve_strings(line) for line in self.lines
            ]
        return self._code_lines_wo_comments

    @property
    def counter_lines(self) -> list[str]:
        """Lines with comments and double-quoted strings masked for metric counters."""
        if self._counter_lines is None:
            states = self.line_string_states
            code_lines = self.code_lines_without_comments
            self._counter_lines = [
                line if states[idx] else mask_double_quoted_strings_preserve_len(line)
                for idx, line in enumerate(code_lines)
            ]
        return self._counter_lines

    @property
    def line_lengths(self) -> list[int]:
        if self._line_lengths is None:
            self._line_lengths = [len(line) for line in self.lines]
        return self._line_lengths

    @property
    def blank_line_flags(self) -> list[bool]:
        if self._blank_line_flags is None:
            self._blank_line_flags = [line.strip() == "" for line in self.lines]
        return self._blank_line_flags

    def ts_nodes_for_types(
        self,
        node_types: set[str],
        *,
        hot_node_types: Iterable[str] = (),
        walker: Callable[[Any], Iterable[Any]],
    ) -> dict[str, list[Any]]:
        """Return CST nodes grouped by type, materialised once per snapshot."""
        root = self.root_node
        if root is None or not isinstance(getattr(root, "text", None), (bytes, bytearray)):
            return {node_type: [] for node_type in node_types}
        if self._ts_node_groups is None:
            collected_types = set(node_types) | set(hot_node_types)
            grouped = {node_type: [] for node_type in collected_types}
            for node in walker(root):
                node_type = getattr(node, "type", None)
                if node_type in grouped:
                    grouped[node_type].append(node)
            self._ts_node_groups = grouped
        else:
            missing = (set(node_types) | set(hot_node_types)) - set(self._ts_node_groups)
            if missing:
                for node_type in missing:
                    self._ts_node_groups[node_type] = []
                for node in walker(root):
                    node_type = getattr(node, "type", None)
                    if node_type in missing:
                        self._ts_node_groups[node_type].append(node)
        return {node_type: self._ts_node_groups.get(node_type, []) for node_type in node_types}

    def complexity_metrics_for_procs(
        self,
        procs: list[ProcInfo],
    ) -> list[tuple[int, int]]:
        """Return cached ``(cognitive, mccabe)`` metrics for procedures."""
        key = tuple((proc.start_idx, proc.end_idx) for proc in procs)
        if self._complexity_metrics_cache is None:
            self._complexity_metrics_cache = {}
        cached = self._complexity_metrics_cache.get(key)
        if cached is not None:
            return cached
        metrics = [
            _calc_complexity_metrics_from_lines(
                self.lines,
                proc.start_idx,
                proc.end_idx,
                masked_lines=self.counter_lines,
                proc_name=proc.name,
            )
            for proc in procs
        ]
        self._complexity_metrics_cache[key] = metrics
        return metrics

    def get_runtime_call_context(self) -> Any | None:
        """Return cached runtime call context if it has been built."""
        return self._runtime_call_context_cache

    def set_runtime_call_context(self, context: Any) -> None:
        """Store shared runtime call context for this snapshot."""
        self._runtime_call_context_cache = context


def build_document_snapshot(
    path: str,
    *,
    content: str,
    tree: Any | None = None,
    parser: BslParser | None = None,
) -> DocumentSnapshot:
    """Build a shared snapshot for one BSL document."""

    effective_parser = parser or BslParser()
    effective_tree = (
        tree if tree is not None else effective_parser.parse_content(content, file_path=path)
    )
    return DocumentSnapshot(path=path, content=content, tree=effective_tree)
