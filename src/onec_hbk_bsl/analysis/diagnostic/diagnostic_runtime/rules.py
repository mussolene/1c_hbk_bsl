from __future__ import annotations

import re
from bisect import bisect_left
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import onec_hbk_bsl.analysis.diagnostics as _diag
from onec_hbk_bsl.analysis.diagnostic.diagnostic_runtime.context import DiagnosticDocumentContext
from onec_hbk_bsl.analysis.diagnostic.diagnostic_runtime.storage import DiagnosticStorage
from onec_hbk_bsl.analysis.diagnostic.domain import ModuleModel
from onec_hbk_bsl.analysis.diagnostic.helpers.config_helpers import (
    config_root_for_file,
    read_text_cached,
)
from onec_hbk_bsl.analysis.diagnostic.models import Diagnostic, Severity
from onec_hbk_bsl.analysis.diagnostic.rules.common_module_rules import (
    _xml_bool_tag,
    common_module_execute_external_code_applicable,
    common_module_xml_for_module_bsl,
)
from onec_hbk_bsl.analysis.diagnostic.rules.module_structure_rules import (
    is_split_module_fragment,
)
from onec_hbk_bsl.analysis.diagnostic.string_state import (
    build_line_string_states,
    comment_start_outside_double_quotes,
)
from onec_hbk_bsl.analysis.lsp_positions import utf8_byte_offset_to_lsp_character


class DiagnosticRuntimeRule:
    code: str

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        raise NotImplementedError


def _path_is_form_module_bsl(path: str) -> bool:
    normalized = path.replace("\\", "/").lower()
    return (
        normalized.endswith("/forms/")
        or "/forms/" in normalized
        and normalized.endswith("/ext/module.bsl")
        or "/forms/" in normalized
        and normalized.endswith("/ext/form/module.bsl")
        or "/forms/" in normalized
        and "/ext/form/" in normalized
        and normalized.endswith(".bsl")
    )


def _path_is_split_module_fragment(path: str) -> bool:
    return is_split_module_fragment(path)


def _path_is_object_module_bsl(path: str) -> bool:
    return path.replace("\\", "/").lower().endswith("/ext/objectmodule.bsl")


def _path_is_whole_module_bsl(path: str) -> bool:
    normalized = path.replace("\\", "/").lower()
    if _path_is_form_module_bsl(path):
        return not _path_is_split_module_fragment(path)
    if "/commonmodules/" in normalized and normalized.endswith("/ext/module.bsl"):
        return True
    if "/ext/" not in normalized:
        return config_root_for_file(path) is None
    if _path_is_split_module_fragment(path):
        return False
    return normalized.endswith(
        (
            "/ext/objectmodule.bsl",
            "/ext/managermodule.bsl",
            "/ext/recordsetmodule.bsl",
            "/ext/valuemanagermodule.bsl",
            "/ext/sessionmodule.bsl",
            "/ext/managedapplicationmodule.bsl",
            "/ext/ordinaryapplicationmodule.bsl",
            "/ext/externalconnectionmodule.bsl",
        )
    )


def _path_is_bsl272_server_only_module(path: str) -> bool:
    normalized = path.replace("\\", "/").lower()
    if "/forms/" in normalized or "/commands/" in normalized:
        return False
    if "/commonmodules/" in normalized:
        xml_path = common_module_xml_for_module_bsl(path)
        if xml_path is None:
            return False
        try:
            raw = xml_path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            return False
        if "<commonmodule" not in raw.casefold():
            return False
        return not (
            _xml_bool_tag(raw, "ClientManagedApplication")
            or _xml_bool_tag(raw, "ClientOrdinaryApplication")
        )
    if re.search(r"(?:^|/)f\d+_module\.bsl$", normalized):
        return True
    return normalized.endswith(
        (
            "objectmodule.bsl",
            "managermodule.bsl",
            "recordsetmodule.bsl",
            "valuemanagermodule.bsl",
            "/objectmodule.bsl",
            "/ext/objectmodule.bsl",
            "/ext/managermodule.bsl",
            "/ext/recordsetmodule.bsl",
            "/ext/valuemanagermodule.bsl",
        )
    )


@lru_cache(maxsize=262_144)
def _code_mask_without_strings_and_comments(line: str, in_string_start: bool = False) -> str:
    out: list[str] = []
    pos = 0
    in_string = in_string_start
    while pos < len(line):
        char = line[pos]
        if in_string:
            out.append(" ")
            if char == '"':
                if pos + 1 < len(line) and line[pos + 1] == '"':
                    out.append(" ")
                    pos += 2
                    continue
                in_string = False
            pos += 1
            continue
        if char == '"':
            in_string = True
            out.append(" ")
            pos += 1
            continue
        if char == "/" and pos + 1 < len(line) and line[pos + 1] == "/":
            out.extend(" " for _ in line[pos:])
            break
        out.append(char)
        pos += 1
    return "".join(out)


def _line_comment(line: str) -> bool:
    return line.lstrip().startswith("//")


def _ts_node_text(node: Any) -> str:
    text = getattr(node, "text", None)
    if text is None:
        return ""
    return text.decode("utf-8", errors="replace") if isinstance(text, bytes) else str(text)


def _ts_walk(node: Any):
    yield node
    for child in getattr(node, "children", []) or []:
        yield from _ts_walk(child)


def _ts_children(node: Any) -> list[Any]:
    return list(getattr(node, "children", []) or [])


def _ts_tree_available(tree: Any) -> bool:
    root = getattr(tree, "root_node", None)
    return root is not None and isinstance(getattr(root, "text", None), (bytes, bytearray))


_BSL030_STATEMENT_TYPES = frozenset(
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


def _bsl030_statement_has_semicolon(node: Any) -> bool:
    return any(getattr(child, "type", None) == ";" for child in _ts_children(node))


def _bsl030_anchor_node(node: Any) -> Any:
    punctuation = {"(", ")", "[", "]", ",", ".", "=", "+", "-", "*", "/", "%"}
    leaves: list[Any] = []
    for child in _ts_walk(node):
        children = _ts_children(child)
        if children:
            continue
        child_type = str(getattr(child, "type", ""))
        text = _ts_node_text(child).strip()
        if not text or child_type in punctuation or text in punctuation or text == ";":
            continue
        leaves.append(child)
    return leaves[-1] if leaves else node


def _diagnostics_bsl030_semicolon_presence(context: DiagnosticDocumentContext) -> list[Diagnostic]:
    root = getattr(context.tree, "root_node", None)
    if root is None:
        return []

    diags: list[Diagnostic] = []
    for node in _ts_walk(root):
        if getattr(node, "type", None) not in _BSL030_STATEMENT_TYPES:
            continue
        if _bsl030_statement_has_semicolon(node):
            continue
        if _diag.tree_has_errors(node):
            continue

        anchor = _bsl030_anchor_node(node)
        start_line = int(anchor.start_point[0]) + 1
        end_line = int(anchor.end_point[0]) + 1
        if not (1 <= start_line <= len(context.lines)) or not (1 <= end_line <= len(context.lines)):
            continue
        character = utf8_byte_offset_to_lsp_character(
            context.lines[start_line - 1], int(anchor.start_point[1])
        )
        end_character = utf8_byte_offset_to_lsp_character(
            context.lines[end_line - 1], int(anchor.end_point[1])
        )
        diags.append(
            Diagnostic(
                file=context.path,
                line=start_line,
                character=character,
                end_line=end_line,
                end_character=end_character,
                severity=Severity.INFORMATION,
                code="BSL030",
                message="Пропущена точка с запятой в конце выражения",
            )
        )
    return diags


def _structural_node_key(
    node: Any,
    cache: dict[int, tuple[Any, ...]] | None = None,
) -> tuple[Any, ...]:
    if cache is not None:
        node_id = id(node)
        cached = cache.get(node_id)
        if cached is not None:
            return cached
    children = _ts_children(node)
    node_type = getattr(node, "type", "")
    if not children:
        text = _ts_node_text(node)
        if node_type == "identifier" or node_type.endswith("_KEYWORD") or node_type == "operator":
            text = text.casefold()
        key = (node_type, text)
    else:
        key = (node_type, tuple(_structural_node_key(child, cache) for child in children))
    if cache is not None:
        cache[node_id] = key
    return key


def _point_char(lines: list[str], point: Any) -> int:
    line_idx = int(point[0])
    byte_col = int(point[1])
    if 0 <= line_idx < len(lines):
        return utf8_byte_offset_to_lsp_character(lines[line_idx], byte_col)
    return byte_col


def _add_node_range(
    storage: DiagnosticStorage,
    *,
    code: str,
    message: str,
    severity: Severity,
    lines: list[str],
    start_node: Any,
    end_node: Any,
) -> None:
    start = start_node.start_point
    end = end_node.end_point
    storage.add_range(
        code=code,
        message=message,
        severity=severity,
        line=int(start[0]),
        character=_point_char(lines, start),
        end_line=int(end[0]),
        end_character=_point_char(lines, end),
    )


def _add_node_start_token_range(
    storage: DiagnosticStorage,
    *,
    code: str,
    message: str,
    severity: Severity,
    lines: list[str],
    node: Any,
) -> None:
    token = next(
        (
            child
            for child in _ts_children(node)
            if getattr(child, "start_point", None) == getattr(node, "start_point", None)
        ),
        node,
    )
    start = token.start_point
    end = token.end_point
    if int(start[0]) != int(end[0]) or _point_char(lines, end) <= _point_char(lines, start):
        end = start
    storage.add_range(
        code=code,
        message=message,
        severity=severity,
        line=int(start[0]),
        character=_point_char(lines, start),
        end_line=int(end[0]),
        end_character=max(_point_char(lines, end), _point_char(lines, start) + 1),
    )


def _diagnostics_bsl042_unused_local_method(context: DiagnosticDocumentContext) -> list[Diagnostic]:
    if _path_is_form_module_bsl(context.path):
        return []
    if _path_is_object_module_bsl(context.path):
        return []
    if not _path_is_whole_module_bsl(context.path):
        return []

    calls = list(getattr(context.snapshot, "calls", []) or [])
    if not context.procedures:
        return []

    called_by_other_proc: set[str] = set()
    for call in calls:
        callee = str(getattr(call, "callee_name", "") or "").casefold()
        if not callee:
            continue
        caller = str(getattr(call, "caller_name", "") or "").casefold()
        if caller and caller == callee:
            continue
        called_by_other_proc.add(callee)

    diags: list[Diagnostic] = []
    for proc in context.procedures:
        name_cf = proc.name.casefold()
        if proc.is_export or name_cf in called_by_other_proc:
            continue
        if _bsl042_is_extension_override(context.lines, proc.start_idx):
            continue
        if _bsl042_is_attachable_method(proc.name):
            continue
        if _bsl042_is_platform_handler(proc.name):
            continue
        start_col, end_col = _diag._proc_name_span(context.lines, proc)
        line_text = context.lines[proc.start_idx] if proc.start_idx < len(context.lines) else ""
        diags.append(
            Diagnostic(
                file=context.path,
                line=proc.start_idx + 1,
                character=start_col,
                end_line=proc.start_idx + 1,
                end_character=end_col or len(line_text),
                severity=Severity.WARNING,
                code="BSL042",
                message=f'Локальный метод "{proc.name}" не используется',
            )
        )
    return diags


def _diagnostics_bsl052_identical_expressions(
    context: DiagnosticDocumentContext,
) -> list[Diagnostic]:
    root = getattr(context.tree, "root_node", None)
    if root is None or not _ts_tree_available(context.tree):
        return []

    storage = DiagnosticStorage(context.path)
    for node in _ts_walk(root):
        if getattr(node, "type", None) != "binary_expression":
            continue
        parts = _bsl052_binary_parts(node)
        if parts is None:
            continue
        left, operator, right = parts
        operator_text = _ts_node_text(operator).casefold()
        if operator_text in {"+", "*", "."}:
            continue
        left_key = _bsl052_expression_key(left)
        right_key = _bsl052_expression_key(right)
        if not left_key or not right_key:
            continue
        duplicate_key = left_key if left_key == right_key else None
        if duplicate_key is None and operator_text in {"и", "and", "или", "or"}:
            duplicate_key = _bsl052_transitive_duplicate_key(node, operator_text)
        if duplicate_key is None:
            continue
        operand_text = _bsl052_operand_display(left if left_key == duplicate_key else right)
        storage.add_range(
            code="BSL052",
            line=int(node.start_point[0]) + 1,
            character=utf8_byte_offset_to_lsp_character(
                context.lines[int(node.start_point[0])], int(node.start_point[1])
            ),
            end_line=int(node.end_point[0]) + 1,
            end_character=utf8_byte_offset_to_lsp_character(
                context.lines[int(node.end_point[0])], int(node.end_point[1])
            ),
            severity=Severity.ERROR,
            message=(
                f'Слева и справа от оператора "{_ts_node_text(operator)}" '
                f'находятся одинаковые подвыражения: "{operand_text}"'
            ),
        )
    return storage.diagnostics


def _bsl052_binary_parts(node: Any) -> tuple[Any, Any, Any] | None:
    children = [
        child
        for child in _ts_children(node)
        if getattr(child, "type", None) not in {"line_comment", "comment"}
    ]
    try:
        op_index = next(
            idx for idx, child in enumerate(children) if getattr(child, "type", None) == "operator"
        )
    except StopIteration:
        return None
    if op_index == 0 or op_index >= len(children) - 1:
        return None
    return children[op_index - 1], children[op_index], children[op_index + 1]


def _bsl052_expression_key(node: Any) -> str:
    return re.sub(r"\s+", "", _ts_node_text(node)).casefold()


def _bsl052_operand_display(node: Any) -> str:
    return " ".join(_ts_node_text(node).split())


def _bsl052_transitive_duplicate_key(node: Any, operator_text: str) -> str | None:
    operands: list[Any] = []

    def collect(current: Any) -> None:
        if getattr(current, "type", None) == "expression":
            expr_children = [
                child
                for child in _ts_children(current)
                if getattr(child, "type", None) not in {"line_comment", "comment"}
            ]
            if len(expr_children) == 1:
                collect(expr_children[0])
                return
        if getattr(current, "type", None) == "binary_expression":
            parts = _bsl052_binary_parts(current)
            if parts is not None and _ts_node_text(parts[1]).casefold() == operator_text:
                collect(parts[0])
                collect(parts[2])
                return
        operands.append(current)

    collect(node)
    seen: set[str] = set()
    for operand in operands:
        key = _bsl052_expression_key(operand)
        if not key:
            continue
        if key in seen:
            return key
        seen.add(key)
    return None


def _bsl042_is_extension_override(lines: list[str], proc_start_idx: int) -> bool:
    idx = proc_start_idx - 1
    while idx >= 0:
        stripped = lines[idx].strip()
        if not stripped or stripped.startswith("//"):
            idx -= 1
            continue
        if not stripped.startswith("&"):
            return False
        annotation = stripped.split("(", 1)[0].casefold()
        if annotation in {
            "&перед",
            "&before",
            "&после",
            "&after",
            "&вместо",
            "&around",
            "&изменениеиконтроль",
            "&changeandvalidate",
        }:
            return True
        idx -= 1
    return False


def _bsl042_is_attachable_method(name: str) -> bool:
    return name.casefold().startswith(("подключаемый_", "attachable_"))


def _bsl042_is_platform_handler(name: str) -> bool:
    return name.casefold() in {
        "присозданииобъекта",
        "передначаломработысистемы",
        "onobjectcreate",
        "beforestart",
    }


def _diagnostics_bsl020_nested_statements(
    context: DiagnosticDocumentContext,
) -> list[Diagnostic] | None:
    root = getattr(getattr(context.tree, "root_node", None), "text", None)
    if not isinstance(root, (bytes, bytearray)) or not _diag._ts_tree_ok_for_rules(context.tree):
        return None

    control_types = {
        "if_statement",
        "while_statement",
        "for_statement",
        "for_each_statement",
        "try_statement",
    }
    storage = DiagnosticStorage(context.path)
    stack: list[Any] = []
    last_entered: Any | None = None
    max_allowed = int(getattr(context.diagnostics_engine, "max_nesting_depth", 4))

    def walk(node: Any) -> None:
        nonlocal last_entered
        is_control = getattr(node, "type", None) in control_types
        if is_control:
            stack.append(node)
            last_entered = node
        for child in _ts_children(node):
            walk(child)
        if is_control:
            if node is last_entered and len(stack) > max_allowed:
                _add_node_start_token_range(
                    storage,
                    code="BSL020",
                    message="Превышен допустимый уровень вложенности управляющих конструкций",
                    severity=Severity.WARNING,
                    lines=context.lines,
                    node=node,
                )
            stack.pop()

    walk(context.tree.root_node)
    return storage.diagnostics


def _diagnostics_bsl173_deleting_collection_item(
    context: DiagnosticDocumentContext,
) -> list[Diagnostic]:
    root = getattr(getattr(context.tree, "root_node", None), "text", None)
    if not isinstance(root, (bytes, bytearray)):
        return []

    storage = DiagnosticStorage(context.path)
    for node in context.ts_nodes_for_types(context.tree, {"for_each_statement"})[
        "for_each_statement"
    ]:
        children = _ts_children(node)
        collection_expr: Any | None = None
        for idx, child in enumerate(children):
            if getattr(child, "type", None) == "IN_KEYWORD":
                collection_expr = next(
                    (
                        candidate
                        for candidate in children[idx + 1 :]
                        if getattr(candidate, "type", None) == "expression"
                    ),
                    None,
                )
                break
        if collection_expr is None:
            continue
        collection_original = _ts_node_text(collection_expr)
        collection_text = collection_original.casefold()
        prefix = f"{collection_text}."
        body_started = False
        for child in children:
            child_type = getattr(child, "type", None)
            if child_type == "DO_KEYWORD":
                body_started = True
                continue
            if child_type == "ENDDO_KEYWORD":
                break
            if not body_started:
                continue
            for call_statement in _ts_walk(child):
                if getattr(call_statement, "type", None) != "call_statement":
                    continue
                call_text = _ts_node_text(call_statement).casefold()
                compact = re.sub(r"\s+", "", call_text)
                if not (
                    compact.startswith(f"{prefix}удалить(")
                    or compact.startswith(f"{prefix}delete(")
                ):
                    continue
                call_expression = next(
                    (
                        child
                        for child in _ts_children(call_statement)
                        if getattr(child, "type", None) == "call_expression"
                    ),
                    call_statement,
                )
                _add_node_range(
                    storage,
                    code="BSL173",
                    message=(
                        f'Не следует удалять элементы коллекции "{collection_original}" '
                        'при ее обходе оператором "Для каждого ... Из ... Цикл"'
                    ),
                    severity=Severity.ERROR,
                    lines=context.lines,
                    start_node=call_statement,
                    end_node=call_expression,
                )
    return storage.diagnostics


def _single_line_call_end(line: str, open_paren: int) -> int:
    depth = 0
    pos = open_paren
    in_string = False
    while pos < len(line):
        char = line[pos]
        if in_string:
            if char == '"':
                if pos + 1 < len(line) and line[pos + 1] == '"':
                    pos += 2
                    continue
                in_string = False
            pos += 1
            continue
        if char == '"':
            if pos + 1 < len(line) and line[pos + 1] == '"':
                pos += 2
                continue
            in_string = True
            pos += 1
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return pos + 1
        pos += 1
    return open_paren + 1


@lru_cache(maxsize=262_144)
def _comment_start_outside_string(line: str) -> int:
    pos = 0
    in_string = False
    while pos < len(line):
        char = line[pos]
        if in_string:
            if char == '"':
                if pos + 1 < len(line) and line[pos + 1] == '"':
                    pos += 2
                    continue
                in_string = False
            pos += 1
            continue
        if char == '"':
            in_string = True
            pos += 1
            continue
        if char == "/" and pos + 1 < len(line) and line[pos + 1] == "/":
            return pos
        pos += 1
    return -1


@lru_cache(maxsize=262_144)
def _code_before_comment(line: str) -> str:
    comment_start = _comment_start_outside_string(line)
    return line if comment_start < 0 else line[:comment_start]


_DOUBLE_QUOTED_STRING_RE = re.compile(r'"(?:[^"]|"")*"')
_BSL005_NETWORK_ADDRESS_RE = re.compile(
    r"(([0-9a-fA-F]{1,4}:){7,7}[0-9a-fA-F]{1,4}|([0-9a-fA-F]{1,4}:){1,7}:"
    r"|([0-9a-fA-F]{1,4}:){1,6}:[0-9a-fA-F]{1,4}|([0-9a-fA-F]{1,4}:){1,5}"
    r"(:[0-9a-fA-F]{1,4}){1,2}|([0-9a-fA-F]{1,4}:){1,4}(:[0-9a-fA-F]{1,4}){1,3}"
    r"|([0-9a-fA-F]{1,4}:){1,3}(:[0-9a-fA-F]{1,4}){1,4}|([0-9a-fA-F]{1,4}:){1,2}"
    r"(:[0-9a-fA-F]{1,4}){1,5}|[0-9a-fA-F]{1,4}:((:[0-9a-fA-F]{1,4}){1,6})"
    r"|(?<![g-zа-яА-ЯёЁ]):((:[0-9a-fA-F]{1,4}){1,7}|\s:)|fe80:(:[0-9a-fA-F]{0,4}){0,4}%[0-9a-zA-Z]{1,}"
    r"|::(ffff(:0{1,4}){0,1}:){0,1}((25[0-5]|(2[0-4]|1{0,1}[0-9]){0,1}[0-9])\.){3,3}"
    r"(25[0-5]|(2[0-4]|1{0,1}[0-9]){0,1}[0-9])|([0-9a-fA-F]{1,4}:){1,4}:"
    r"((25[0-5]|(2[0-4]|1{0,1}[0-9]){0,1}[0-9])\.){3,3}"
    r"(25[0-5]|(2[0-4]|1{0,1}[0-9]){0,1}[0-9]))"
    r"|((25[0-5]|(2[0-4]|1{0,1}[0-9]){0,1}[0-9])\.){3,3}"
    r"(25[0-5]|(2[0-4]|1{0,1}[0-9]){0,1}[0-9])",
    re.IGNORECASE,
)
_BSL005_URL_RE = re.compile(r"^(ftp|http|https)://[^ \"].*", re.IGNORECASE)
_BSL005_ALPHABET_RE = re.compile(r"[A-zА-я]", re.IGNORECASE)
_BSL005_POPULAR_VERSION_RE = re.compile(r"^(?:1|2|3|8\.3|11)\.")
_BSL005_LINE_EXCLUSION_RE = re.compile(
    r"ЗапуститьПриложение|RunApp|Пространств|Namespace|Драйвер|Driver",
    re.IGNORECASE,
)
_BSL005_PARAM_VERSION_RE = re.compile(r"Верси|Version", re.IGNORECASE)

_BSL006_UNIX_STD_ROOT_RE = re.compile(
    r"^/(bin|boot|dev|etc|home|lib|lost\+found|misc|mnt|media|opt|proc|root|run|sbin|tmp|usr|var)(?:/|$)",
    re.IGNORECASE,
)
_BSL006_URL_RE = re.compile(r"^(ftp|http|https)://[^ \"].*", re.IGNORECASE)

_BSL024_GOOD_STRICT_RE = re.compile(
    r"(?:(?://[ \t].*)|(?:/{2,}[ \t]*))$",
    re.IGNORECASE,
)
_BSL024_COMMENTED_CODE_RE = re.compile(
    r"^\s*//\s*(?:"
    r"(?:Процедура|Функция|Function|Procedure)\s+\w+\s*\("
    r"|(?:КонецПроцедуры|КонецФункции|EndProcedure|EndFunction)\s*;?\s*$"
    r"|(?:Перем|Var)\s+\w+"
    r"|(?:ВЫБРАТЬ|SELECT)\b"
    r"|(?:Если|If|ИначеЕсли|ElseIf|ElsIf|КонецЕсли|EndIf)\b"
    r"|[A-Za-zА-Яа-яЁё_]\w*(?:\.[A-Za-zА-Яа-яЁё_]\w*)*\s*\("
    r"|\w.*(?:;|:=)"
    r")",
    re.IGNORECASE,
)
_BSL178_DEPRECATED_METHOD_RE = re.compile(
    r"(?<!\.)(?<!\w)\b("
    r"КраткоеПредставлениеОшибки|BriefErrorDescription|"
    r"ПодробноеПредставлениеОшибки|DetailErrorDescription|"
    r"ПоказатьИнформациюОбОшибке|ShowErrorInfo"
    r")\s*\(",
    re.IGNORECASE,
)
_BSL178_MIN_COMPATIBILITY = (8, 3, 17)
_CONFIG_COMPATIBILITY_RE = re.compile(
    r"<(?:ConfigurationExtensionCompatibilityMode|CompatibilityMode)>\s*"
    r"Version(?P<major>\d+)_(?P<minor>\d+)_(?P<patch>\d+)\s*"
    r"</(?:ConfigurationExtensionCompatibilityMode|CompatibilityMode)>",
    re.IGNORECASE,
)
_BSL177_METHOD_REPLACEMENTS: dict[str, str] = {
    "установитькраткийзаголовокприложения": "КлиентскоеПриложение.УстановитьКраткийЗаголовок",
    "получитькраткийзаголовокприложения": "КлиентскоеПриложение.ПолучитьКраткийЗаголовок",
    "установитьзаголовокклиентскогоприложения": "КлиентскоеПриложение.УстановитьЗаголовок",
    "получитьзаголовокклиентскогоприложения": "КлиентскоеПриложение.ПолучитьЗаголовок",
    "текущийвариантосновногошрифтаклиентскогоприложения": (
        "КлиентскоеПриложение.ТекущийВариантОсновногоШрифта"
    ),
    "текущийвариантинтерфейсаклиентскогоприложения": (
        "КлиентскоеПриложение.ТекущийВариантИнтерфейса"
    ),
    "setshortapplicationcaption": "ClientApplication.SetShortCaption",
    "getshortapplicationcaption": "ClientApplication.GetShortCaption",
    "setclientapplicationcaption": "ClientApplication.SetCaption",
    "getclientapplicationcaption": "ClientApplication.GetCaption",
    "clientapplicationbasefontcurrentvariant": "ClientApplication.CurrentBaseFontVariant",
    "clientapplicationinterfacecurrentvariant": "ClientApplication.CurrentInterfaceVariant",
}
_BSL177_DEPRECATED_METHOD_RE = re.compile(
    r"(?<!\.)(?<!\w)\b("
    r"УстановитьКраткийЗаголовокПриложения|ПолучитьКраткийЗаголовокПриложения|"
    r"УстановитьЗаголовокКлиентскогоПриложения|ПолучитьЗаголовокКлиентскогоПриложения|"
    r"ТекущийВариантОсновногоШрифтаКлиентскогоПриложения|"
    r"ТекущийВариантИнтерфейсаКлиентскогоПриложения|"
    r"SetShortApplicationCaption|GetShortApplicationCaption|"
    r"SetClientApplicationCaption|GetClientApplicationCaption|"
    r"ClientApplicationBaseFontCurrentVariant|ClientApplicationInterfaceCurrentVariant"
    r")\s*\(",
    re.IGNORECASE | re.UNICODE,
)
_BSL195_GET_FORM_RE = re.compile(r"\b(ПолучитьФорму|GetForm)\s*\(", re.IGNORECASE | re.UNICODE)
_BSL179_MANAGED_FORM_RE = re.compile(
    r"\b(?:Тип|Type)\s*\(\s*(\"(?:УправляемаяФорма|ManagedForm)\")\s*\)",
    re.IGNORECASE | re.UNICODE,
)


@lru_cache(maxsize=128)
def _bsl178_applicable_for_path(path: str) -> bool:
    config_root = config_root_for_file(path)
    if config_root is None:
        return True
    raw = read_text_cached(str(Path(config_root) / "Configuration.xml"))
    match = _CONFIG_COMPATIBILITY_RE.search(raw)
    if match is None:
        return True
    version = (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
    )
    return version >= _BSL178_MIN_COMPATIBILITY


_BSL180_DISABLE_SAFE_MODE_RE = re.compile(
    r"(?<!\.)(?<!\w)\b("
    r"УстановитьБезопасныйРежим|SetSafeMode|"
    r"УстановитьОтключениеБезопасногоРежима|SetSafeModeDisabled"
    r")\s*\(\s*([^)]*)\)",
    re.IGNORECASE | re.UNICODE,
)
_BSL185_EXTERNAL_APP_RE = re.compile(
    r"\b("
    r"КомандаСистемы|System|ЗапуститьСистему|RunSystem|ЗапуститьПриложение|RunApp|"
    r"НачатьЗапускПриложения|BeginRunningApplication|"
    r"ЗапуститьПриложениеАсинх|RunAppAsync|ЗапуститьПрограмму|ОткрытьПроводник|ОткрытьФайл"
    r")\s*\(",
    re.IGNORECASE | re.UNICODE,
)
_BSL188_FILESYSTEM_METHOD_NAMES = frozenset(
    name.casefold()
    for name in (
        "ЗначениеВФайл",
        "ValueToFile",
        "КопироватьФайл",
        "FileCopy",
        "ОбъединитьФайлы",
        "MergeFiles",
        "ПереместитьФайл",
        "MoveFile",
        "РазделитьФайл",
        "SplitFile",
        "СоздатьКаталог",
        "CreateDirectory",
        "УдалитьФайлы",
        "DeleteFiles",
        "КаталогПрограммы",
        "BinDir",
        "КаталогВременныхФайлов",
        "TempFilesDir",
        "КаталогДокументов",
        "DocumentsDir",
        "РабочийКаталогДанныхПользователя",
        "UserDataWorkDir",
        "НачатьПодключениеРасширенияРаботыСФайлами",
        "BeginAttachingFileSystemExtension",
        "НачатьУстановкуРасширенияРаботыСФайлами",
        "BeginInstallFileSystemExtension",
        "УстановитьРасширениеРаботыСФайлами",
        "InstallFileSystemExtension",
        "УстановитьРасширениеРаботыСФайламиАсинх",
        "InstallFileSystemExtensionAsync",
        "ПодключитьРасширениеРаботыСФайламиАсинх",
        "AttachFileSystemExtensionAsync",
        "КаталогВременныхФайловАсинх",
        "TempFilesDirAsync",
        "КаталогДокументовАсинх",
        "DocumentsDirAsync",
        "НачатьПолучениеКаталогаВременныхФайлов",
        "BeginGettingTempFilesDir",
        "НачатьПолучениеКаталогаДокументов",
        "BeginGettingDocumentsDir",
        "НачатьПолучениеРабочегоКаталогаДанныхПользователя",
        "BeginGettingUserDataWorkDir",
        "РабочийКаталогДанныхПользователяАсинх",
        "UserDataWorkDirAsync",
        "КопироватьФайлАсинх",
        "CopyFileAsync",
        "НайтиФайлыАсинх",
        "FindFilesAsync",
        "НачатьКопированиеФайла",
        "BeginCopyingFile",
        "НачатьПеремещениеФайла",
        "BeginMovingFile",
        "НачатьПоискФайлов",
        "BeginFindingFiles",
        "НачатьСозданиеДвоичныхДанныхИзФайла",
        "BeginCreateBinaryDataFromFile",
        "НачатьСозданиеКаталога",
        "BeginCreatingDirectory",
        "НачатьУдалениеФайлов",
        "BeginDeletingFiles",
        "ПереместитьФайлАсинх",
        "MoveFileAsync",
        "СоздатьДвоичныеДанныеИзФайлаАсинх",
        "CreateBinaryDataFromFileAsync",
        "СоздатьКаталогАсинх",
        "CreateDirectoryAsync",
        "УдалитьФайлыАсинх",
        "DeleteFilesAsync",
    )
)
_BSL188_FILESYSTEM_NEW_NAMES = frozenset(
    name.casefold()
    for name in (
        "File",
        "Файл",
        "xBase",
        "HTMLWriter",
        "ЗаписьHTML",
        "HTMLReader",
        "ЧтениеHTML",
        "FastInfosetReader",
        "ЧтениеFastInfoset",
        "FastInfosetWriter",
        "ЗаписьFastInfoset",
        "XSLTransform",
        "ПреобразованиеXSL",
        "ZipFileWriter",
        "ЗаписьZipФайла",
        "ZipFileReader",
        "ЧтениеZipФайла",
        "TextReader",
        "ЧтениеТекста",
        "TextWriter",
        "ЗаписьТекста",
        "TextExtraction",
        "ИзвлечениеТекста",
        "BinaryData",
        "ДвоичныеДанные",
        "FileStream",
        "ФайловыйПоток",
        "FileStreamsManager",
        "МенеджерФайловыхПотоков",
        "DataWriter",
        "ЗаписьДанных",
        "DataReader",
        "ЧтениеДанных",
    )
)
_BSL203_INTERNET_NEW_NAMES = frozenset(
    name.casefold()
    for name in (
        "FTPСоединение",
        "FTPConnection",
        "HTTPСоединение",
        "HTTPConnection",
        "WSОпределения",
        "WSDefinitions",
        "WSПрокси",
        "WSProxy",
        "ИнтернетПочтовыйПрофиль",
        "InternetMailProfile",
        "ИнтернетПочта",
        "InternetMail",
        "Почта",
        "Mail",
        "HTTPЗапрос",
        "HTTPRequest",
        "ИнтернетПрокси",
        "InternetProxy",
    )
)
_BSL264_SYSTEM_INFO_NEW_NAMES = frozenset(
    name.casefold() for name in ("СистемнаяИнформация", "SystemInfo")
)
_BSL205_ROLE_AVAILABLE_RE = re.compile(
    r"(?<!\.)(?<!\w)\b(РольДоступна|IsInRole)\s*\(",
    re.IGNORECASE | re.UNICODE,
)
_BSL205_PRIVILEGED_MODE_RE = re.compile(
    r"(?<!\.)(?<!\w)\b(ПривилегированныйРежим|PrivilegedMode)\s*\(",
    re.IGNORECASE | re.UNICODE,
)
_BSL205_ASSIGNMENT_RE = re.compile(
    r"^\s*([А-ЯЁа-яёA-Za-z_][А-ЯЁа-яёA-Za-z_0-9]*)\s*=",
    re.UNICODE,
)
_BSL205_IF_RE = re.compile(
    r"^\s*(?:Если|If|ИначеЕсли|ElsIf)\s+(.*?)(?:\bТогда\b|\bThen\b)",
    re.IGNORECASE | re.UNICODE,
)
_BSL258_UNION_RE = re.compile(r"\b(?:ОБЪЕДИНИТЬ|UNION)\b(?!\s+(?:ВСЕ|ALL)\b)", re.IGNORECASE)
_BSL183_EXECUTE_EXTERNAL_CODE_RE = re.compile(
    r"(?<![.\w])(Выполнить|Execute|Вычислить|Eval)\s*\(",
    re.IGNORECASE | re.UNICODE,
)
_BSL226_OS_USERS_RE = re.compile(
    r"(?<![.\w])(ПользователиОС|OSUsers)\s*\(",
    re.IGNORECASE | re.UNICODE,
)
_BSL247_SET_PRIVILEGED_RE = re.compile(
    r"(?<![.\w])(УстановитьПривилегированныйРежим|SetPrivilegedMode)\s*\(([^)]*)\)",
    re.IGNORECASE | re.UNICODE,
)
_BSL250_TEMPFILES_RE = re.compile(
    r"(?<![.\w])(КаталогВременныхФайлов|TempFilesDir)\s*\(",
    re.IGNORECASE | re.UNICODE,
)
_BSL267_EXTERNAL_CODE_TOOLS_RE = re.compile(
    r"(?<![.\w])"
    r"(ВнешниеОбработки|ExternalDataProcessors|ВнешниеОтчеты|ExternalReports|"
    r"РасширенияКонфигурации|ConfigurationExtensions)"
    r"\s*\.\s*(Создать|Create|Подключить|Connect)\s*\(",
    re.IGNORECASE | re.UNICODE,
)
_METHOD_CHAIN_RE = re.compile(r"\s*\.\s*[А-ЯЁа-яёA-Za-z_][А-ЯЁа-яёA-Za-z_0-9]*\s*\(", re.UNICODE)
_BSL272_SYNC_REPLACEMENTS: dict[str, str] = {
    "ВОПРОС": "ПоказатьВопрос",
    "DOQUERYBOX": "ShowQueryBox",
    "ОТКРЫТЬФОРМУМОДАЛЬНО": "ОткрытьФорму",
    "OPENFORMMODAL": "OpenForm",
    "ОТКРЫТЬЗНАЧЕНИЕ": "ПоказатьЗначение",
    "OPENVALUE": "ShowValue",
    "ПРЕДУПРЕЖДЕНИЕ": "ПоказатьПредупреждение",
    "DOMESSAGEBOX": "ShowMessageBox",
    "ВВЕСТИДАТУ": "ПоказатьВводДаты",
    "INPUTDATE": "ShowInputDate",
    "ВВЕСТИЗНАЧЕНИЕ": "ПоказатьВводЗначения",
    "INPUTVALUE": "ShowInputValue",
    "ВВЕСТИСТРОКУ": "ПоказатьВводСтроки",
    "INPUTSTRING": "ShowInputString",
    "ВВЕСТИЧИСЛО": "ПоказатьВводЧисла",
    "INPUTNUMBER": "ShowInputNumber",
    "УСТАНОВИТЬВНЕШНЮЮКОМПОНЕНТУ": "НачатьУстановкуВнешнейКомпоненты",
    "INSTALLADDIN": "BeginInstallAddIn",
    "УСТАНОВИТЬРАСШИРЕНИЕРАБОТЫСФАЙЛАМИ": "НачатьУстановкуРасширенияРаботыСФайлами",
    "INSTALLFILESYSTEMEXTENSION": "BeginInstallFileSystemExtension",
    "УСТАНОВИТЬРАСШИРЕНИЕРАБОТЫСКРИПТОГРАФИЕЙ": "НачатьУстановкуРасширенияРаботыСКриптографией",
    "INSTALLCRYPTOEXTENSION": "BeginInstallCryptoExtension",
    "ПОДКЛЮЧИТЬРАСШИРЕНИЕРАБОТЫСКРИПТОГРАФИЕЙ": "НачатьПодключениеРасширенияРаботыСКриптографией",
    "ATTACHCRYPTOEXTENSION": "BeginAttachingCryptoExtension",
    "ПОДКЛЮЧИТЬРАСШИРЕНИЕРАБОТЫСФАЙЛАМИ": "НачатьПодключениеРасширенияРаботыСФайлами",
    "ATTACHFILESYSTEMEXTENSION": "BeginAttachingFileSystemExtension",
    "ПОМЕСТИТЬФАЙЛ": "НачатьПомещениеФайла",
    "PUTFILE": "BeginPutFile",
    "КОПИРОВАТЬФАЙЛ": "НачатьКопированиеФайла",
    "FILECOPY": "BeginCopyingFile",
    "ПЕРЕМЕСТИТЬФАЙЛ": "НачатьПеремещениеФайла",
    "MOVEFILE": "BeginMovingFile",
    "НАЙТИФАЙЛЫ": "НачатьПоискФайлов",
    "FINDFILES": "BeginFindingFiles",
    "УДАЛИТЬФАЙЛЫ": "НачатьУдалениеФайлов",
    "DELETEFILES": "BeginDeletingFiles",
    "СОЗДАТЬКАТАЛОГ": "НачатьСозданиеКаталога",
    "CREATEDIRECTORY": "BeginCreatingDirectory",
    "КАТАЛОГВРЕМЕННЫХФАЙЛОВ": "НачатьПолучениеКаталогаВременныхФайлов",
    "TEMPFILESDIR": "BeginGettingTempFilesDir",
    "КАТАЛОГДОКУМЕНТОВ": "НачатьПолучениеКаталогаДокументов",
    "DOCUMENTSDIR": "BeginGettingDocumentsDir",
    "РАБОЧИЙКАТАЛОГДАННЫХПОЛЬЗОВАТЕЛЯ": "НачатьПолучениеРабочегоКаталогаДанныхПользователя",
    "USERDATAWORKDIR": "BeginGettingUserDataWorkDir",
    "ПОЛУЧИТЬФАЙЛЫ": "НачатьПолучениеФайлов",
    "GETFILES": "BeginGettingFiles",
    "ПОМЕСТИТЬФАЙЛЫ": "НачатьПомещениеФайлов",
    "PUTFILES": "BeginPuttingFiles",
    "ЗАПРОСИТЬРАЗРЕШЕНИЕПОЛЬЗОВАТЕЛЯ": "НачатьЗапросРазрешенияПользователя",
    "REQUESTUSERPERMISSION": "BeginRequestingUserPermission",
    "ЗАПУСТИТЬПРИЛОЖЕНИЕ": "НачатьЗапускПриложения",
    "RUNAPP": "BeginRunningApplication",
}
_BSL272_SYNC_RE = re.compile(
    r"(?<![.\w])(?P<name>"
    + "|".join(re.escape(key) for key in sorted(_BSL272_SYNC_REPLACEMENTS, key=len, reverse=True))
    + r")\s*\(",
    re.IGNORECASE | re.UNICODE,
)
_QUERY_VIRTUAL_TABLE_NAME_PATTERN = (
    r"(?:Регистр(?:Сведений|Накопления|Бухгалтерии|Расчета)|"
    r"InformationRegister|AccumulationRegister|AccountingRegister|CalculationRegister)"
    r"\.\w+(?:\.\w+)+"
)
_BSL273_VIRTUAL_TABLE_RE = re.compile(
    rf"\b(?P<name>{_QUERY_VIRTUAL_TABLE_NAME_PATTERN})(?!\.)\s*(?P<open>\()?",
    re.IGNORECASE | re.UNICODE,
)
_BSL279_IDENTIFIER_RE = re.compile(r"\b\w*[ёЁ]\w*\b", re.UNICODE)
_BSL277_ROLLBACK_NAMES = frozenset({"отменитьтранзакцию", "rollbacktransaction"})
_BSL276_PROCEED_NAMES = frozenset({"продолжитьвызов", "proceedwithcall"})
_BSL276_AROUND_ANNOTATION_RE = re.compile(r"^\s*&(?:Вместо|Instead|Around)\b", re.IGNORECASE)
_BSL255_NUMBER_NAMES = frozenset({"число", "number"})
_BSL060_MESSAGE = "Использование двойных отрицаний усложняет понимание кода"


def bsl024_find_report_comment_col(
    line: str, comment_start: int | None = None, *, comment_start_known: bool = False
) -> int | None:
    col = comment_start if comment_start_known else _comment_start_outside_string(line)
    if col is None or col < 0:
        return None
    comment_text = line[col:]
    if _BSL024_GOOD_STRICT_RE.match(comment_text):
        return None
    rest = comment_text[2:].lstrip()
    if rest.startswith("@") or rest.lower().startswith("(c)") or rest.startswith("©"):
        return None
    if (
        comment_text.startswith("//!")
        or re.match(r"//\s*noqa\b", comment_text, re.IGNORECASE)
        or re.match(r"//\s*bsl-disable\b", comment_text, re.IGNORECASE)
    ):
        return None
    is_full_line_comment = col == len(line) - len(line.lstrip())
    if (
        is_full_line_comment
        and not re.match(r"//\s*(?:Возврат|Return)\b", comment_text, re.IGNORECASE)
        and _BSL024_COMMENTED_CODE_RE.match(comment_text)
    ):
        return None
    if is_full_line_comment and (
        re.match(r'//\s*"\s*(?:ВЫБРАТЬ|SELECT)\b', comment_text, re.IGNORECASE)
        or re.match(r"//\s*\)\s*;?\s*$", comment_text)
    ):
        return None
    if is_full_line_comment and rest.startswith("&"):
        return None
    return col


def _call_chain_end(line: str, open_paren: int) -> int:
    end = _single_line_call_end(line, open_paren)
    while True:
        match = _METHOD_CHAIN_RE.match(line, end)
        if match is None:
            return end
        end = _single_line_call_end(line, match.end() - 1)


def _multi_line_call_end(lines: list[str], start_line: int, open_paren: int) -> tuple[int, int]:
    depth = 0
    line_idx = start_line
    pos = open_paren
    while line_idx < len(lines):
        line = lines[line_idx]
        while pos < len(line):
            char = line[pos]
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    return line_idx, pos + 1
            pos += 1
        line_idx += 1
        pos = 0
    return start_line, open_paren + 1


def bsl024_should_report_line(line: str) -> bool:
    return bsl024_find_report_comment_col(line) is not None


@dataclass(frozen=True)
class _TernarySpan:
    start: int
    end: int
    line: int
    col: int
    end_line: int
    end_col: int


def _skip_string(text: str, pos: int) -> int:
    quote = text[pos]
    pos += 1
    while pos < len(text):
        if text[pos] == quote:
            if quote == '"' and pos + 1 < len(text) and text[pos + 1] == '"':
                pos += 2
                continue
            return pos + 1
        pos += 1
    return pos


def _matching_paren(text: str, open_pos: int) -> int:
    depth = 1
    pos = open_pos + 1
    while pos < len(text):
        char = text[pos]
        if char in ('"', "'"):
            pos = _skip_string(text, pos)
            continue
        if char == "/" and pos + 1 < len(text) and text[pos + 1] == "/":
            newline = text.find("\n", pos)
            if newline < 0:
                return len(text)
            pos = newline + 1
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return pos + 1
        pos += 1
    return len(text)


def _split_top_level_args(text: str) -> list[str]:
    args: list[str] = []
    start = 0
    depth = 0
    pos = 0
    while pos < len(text):
        char = text[pos]
        if char in ('"', "'"):
            pos = _skip_string(text, pos)
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            args.append(text[start:pos])
            start = pos + 1
        pos += 1
    args.append(text[start:])
    return args


def _calls_in_node(
    parent: Any,
    calls: list[dict[str, Any]],
    starts: list[int] | None = None,
) -> list[dict[str, Any]]:
    start = getattr(parent, "start_byte", None)
    end = getattr(parent, "end_byte", None)
    if start is None or end is None:
        return []
    effective_starts = starts or [getattr(call["node"], "start_byte", -1) for call in calls]
    left = bisect_left(effective_starts, start)
    right = bisect_left(effective_starts, end)
    return calls[left:right]


def _ternary_spans(context: DiagnosticDocumentContext) -> list[_TernarySpan]:
    spans: list[_TernarySpan] = []
    pos = 0
    text = context.content
    while pos < len(text):
        char = text[pos]
        if char in ('"', "'"):
            pos = _skip_string(text, pos)
            continue
        if char == "/" and pos + 1 < len(text) and text[pos + 1] == "/":
            newline = text.find("\n", pos)
            pos = len(text) if newline < 0 else newline + 1
            continue
        if char == "?":
            open_pos = pos + 1
            while open_pos < len(text) and text[open_pos].isspace():
                open_pos += 1
            if open_pos < len(text) and text[open_pos] == "(":
                end = _matching_paren(text, open_pos)
                line, col = context.to_line_col(pos)
                end_line, end_col = context.to_line_col(end)
                spans.append(_TernarySpan(pos, end, line, col, end_line, end_col))
                pos += 1
                continue
        pos += 1
    return spans


class BadWordsRule(DiagnosticRuntimeRule):
    code = "BSL150"

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        rx = getattr(context.diagnostics_engine, "_bad_words_re", None)
        if rx is None:
            return []
        find_in_comments = bool(
            getattr(context.diagnostics_engine, "bad_words_find_in_comments", True)
        )
        if find_in_comments:
            comment_starts = [None] * len(context.lines)
        elif context.snapshot is not None:
            comment_starts = list(context.snapshot.comment_starts)
        else:
            string_states = build_line_string_states(context.lines)
            comment_starts = [
                comment_start_outside_double_quotes(line, string_states[idx])
                for idx, line in enumerate(context.lines)
            ]
        storage = DiagnosticStorage(context.path)
        for line_idx, line in enumerate(context.lines):
            if not line:
                continue
            comment_start = comment_starts[line_idx]
            for match in rx.finditer(line):
                if comment_start is not None and match.start() >= comment_start:
                    continue
                word = match.group(0)
                storage.add_match(
                    code=self.code,
                    message=f"В тексте модуля найдено запрещенное слово <{word}>.",
                    severity=Severity.WARNING,
                    line=line_idx,
                    start=match.start(),
                    end=match.end(),
                )
        return storage.diagnostics


class CanonicalSpellingKeywordsRule(DiagnosticRuntimeRule):
    code = "BSL153"
    _bool_op_re = re.compile(r"\b(?:И|And|ИЛИ|Or)\b", re.IGNORECASE | re.UNICODE)
    _if_start_re = re.compile(r"^\s*(?:Если|If|ИначеЕсли|ElsIf|ElseIf)\b", re.IGNORECASE)
    _then_re = re.compile(r"\b(?:Тогда|Then)\b", re.IGNORECASE)
    _accepted: dict[str, frozenset[str]] = {
        "если": frozenset({"Если", "If"}),
        "if": frozenset({"If"}),
        "тогда": frozenset({"Тогда", "Then"}),
        "then": frozenset({"Then"}),
        "иначе": frozenset({"Иначе", "Else"}),
        "else": frozenset({"Else"}),
        "иначеесли": frozenset({"ИначеЕсли", "ElsIf", "ElseIf"}),
        "elsif": frozenset({"ElsIf"}),
        "elseif": frozenset({"ElseIf"}),
        "конецесли": frozenset({"КонецЕсли", "EndIf"}),
        "endif": frozenset({"EndIf"}),
        "для": frozenset({"Для", "For"}),
        "for": frozenset({"For"}),
        "каждого": frozenset({"Каждого", "каждого", "Each", "each"}),
        "each": frozenset({"Each", "each"}),
        "из": frozenset({"Из", "In"}),
        "in": frozenset({"In"}),
        "цикл": frozenset({"Цикл", "Do"}),
        "do": frozenset({"Do"}),
        "пока": frozenset({"Пока", "While"}),
        "while": frozenset({"While"}),
        "прервать": frozenset({"Прервать", "Break"}),
        "break": frozenset({"Break"}),
        "продолжить": frozenset({"Продолжить", "Continue"}),
        "continue": frozenset({"Continue"}),
        "конеццикла": frozenset({"КонецЦикла", "EndDo"}),
        "enddo": frozenset({"EndDo"}),
        "по": frozenset({"По", "To"}),
        "to": frozenset({"To"}),
        "процедура": frozenset({"Процедура", "Procedure"}),
        "procedure": frozenset({"Procedure"}),
        "знач": frozenset({"Знач", "Val"}),
        "val": frozenset({"Val"}),
        "экспорт": frozenset({"Экспорт", "Export"}),
        "export": frozenset({"Export"}),
        "перем": frozenset({"Перем", "Var"}),
        "var": frozenset({"Var"}),
        "попытка": frozenset({"Попытка", "Try"}),
        "try": frozenset({"Try"}),
        "выполнить": frozenset({"Выполнить", "Execute"}),
        "execute": frozenset({"Execute"}),
        "возврат": frozenset({"Возврат", "Return"}),
        "return": frozenset({"Return"}),
        "истина": frozenset({"Истина", "True"}),
        "true": frozenset({"True"}),
        "исключение": frozenset({"Исключение", "Except"}),
        "except": frozenset({"Except"}),
        "вызватьисключение": frozenset({"ВызватьИсключение", "Raise"}),
        "raise": frozenset({"Raise"}),
        "конецпопытки": frozenset({"КонецПопытки", "EndTry"}),
        "endtry": frozenset({"EndTry"}),
        "конецпроцедуры": frozenset({"КонецПроцедуры", "EndProcedure"}),
        "endprocedure": frozenset({"EndProcedure"}),
        "функция": frozenset({"Функция", "Function"}),
        "function": frozenset({"Function"}),
        "конецфункции": frozenset({"КонецФункции", "EndFunction"}),
        "endfunction": frozenset({"EndFunction"}),
        "ложь": frozenset({"Ложь", "False"}),
        "false": frozenset({"False"}),
        "добавитьобработчик": frozenset({"ДобавитьОбработчик", "AddHandler"}),
        "addhandler": frozenset({"AddHandler"}),
        "удалитьобработчик": frozenset({"УдалитьОбработчик", "RemoveHandler"}),
        "removehandler": frozenset({"RemoveHandler"}),
        "перейти": frozenset({"Перейти", "Goto"}),
        "goto": frozenset({"Goto"}),
        "и": frozenset({"И"}),
        "and": frozenset({"And", "AND"}),
        "или": frozenset({"Или", "ИЛИ"}),
        "or": frozenset({"Or", "OR"}),
        "не": frozenset({"Не", "НЕ"}),
        "not": frozenset({"Not", "NOT"}),
        "новый": frozenset({"Новый", "New"}),
        "new": frozenset({"New"}),
        "неопределено": frozenset({"Неопределено", "Undefined"}),
        "undefined": frozenset({"Undefined"}),
        "область": frozenset({"Область", "Region"}),
        "region": frozenset({"Region"}),
        "конецобласти": frozenset({"КонецОбласти", "EndRegion"}),
        "endregion": frozenset({"EndRegion"}),
        "сервер": frozenset({"Сервер", "Server"}),
        "server": frozenset({"Server"}),
        "клиент": frozenset({"Клиент", "Client"}),
        "client": frozenset({"Client"}),
        "мобильноеприложениеклиент": frozenset({"МобильноеПриложениеКлиент", "MobileAppClient"}),
        "mobileappclient": frozenset({"MobileAppClient"}),
        "мобильноеприложениесервер": frozenset({"МобильноеПриложениеСервер", "MobileAppServer"}),
        "mobileappserver": frozenset({"MobileAppServer"}),
        "мобильныйклиент": frozenset({"МобильныйКлиент", "MobileClient"}),
        "mobileclient": frozenset({"MobileClient"}),
        "толстыйклиентобычноеприложение": frozenset(
            {"ТолстыйКлиентОбычноеПриложение", "ThickClientOrdinaryApplication"}
        ),
        "thickclientordinaryapplication": frozenset({"ThickClientOrdinaryApplication"}),
        "толстыйклиентуправляемоеприложение": frozenset(
            {"ТолстыйКлиентУправляемоеПриложение", "ThickClientManagedApplication"}
        ),
        "thickclientmanagedapplication": frozenset({"ThickClientManagedApplication"}),
        "внешнеесоединение": frozenset({"ВнешнееСоединение", "ExternalConnection"}),
        "externalconnection": frozenset({"ExternalConnection"}),
        "тонкийклиент": frozenset({"ТонкийКлиент", "ThinClient"}),
        "thinclient": frozenset({"ThinClient"}),
        "вебклиент": frozenset({"ВебКлиент", "WebClient"}),
        "webclient": frozenset({"WebClient"}),
        "наклиенте": frozenset({"НаКлиенте", "AtClient"}),
        "atclient": frozenset({"AtClient"}),
        "насервере": frozenset({"НаСервере", "AtServer"}),
        "atserver": frozenset({"AtServer"}),
        "насерверебезконтекста": frozenset({"НаСервереБезКонтекста", "AtServerNoContext"}),
        "atservernocontext": frozenset({"AtServerNoContext"}),
        "наклиентенасерверебезконтекста": frozenset(
            {"НаКлиентеНаСервереБезКонтекста", "AtClientAtServerNoContext"}
        ),
        "atclientatservernocontext": frozenset({"AtClientAtServerNoContext"}),
        "наклиентенасервере": frozenset({"НаКлиентеНаСервере", "AtClientAtServer"}),
        "atclientatserver": frozenset({"AtClientAtServer"}),
    }
    _word_re = re.compile(
        r"\b(?:"
        + "|".join(re.escape(key) for key in sorted(_accepted, key=len, reverse=True))
        + r")\b",
        re.IGNORECASE | re.UNICODE,
    )

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        if _path_is_form_module_bsl(context.path):
            return []
        skipped_lines = self._bsl036_condition_lines(context) if context.bsl036_enabled else set()
        storage = DiagnosticStorage(context.path)
        for idx, line in enumerate(context.lines):
            if _line_comment(line) or idx in skipped_lines:
                continue
            if not self._word_re.search(line):
                continue
            clean = _code_mask_without_strings_and_comments(line)
            for match in self._word_re.finditer(clean):
                word = match.group()
                if word in self._accepted.get(word.lower(), ()):
                    continue
                storage.add_match(
                    code=self.code,
                    line=idx,
                    start=match.start(),
                    end=match.end(),
                    severity=Severity.INFORMATION,
                    message=f'Ключевое слово "{word}" написано не канонически',
                )
        return storage.diagnostics

    @classmethod
    def _bsl036_condition_lines(cls, context: DiagnosticDocumentContext) -> set[int]:
        skipped: set[int] = set()
        for start, line in enumerate(context.lines):
            if not cls._if_start_re.match(line):
                continue
            chunk_lines: list[str] = []
            end = start
            while end < len(context.lines):
                chunk_lines.append(context.lines[end])
                if cls._then_re.search(context.lines[end]):
                    break
                end += 1
            chunk = "\n".join(chunk_lines)
            if len(cls._bool_op_re.findall(chunk)) <= context.max_bool_ops:
                continue
            skipped.update(range(start, min(end + 1, len(context.lines))))
        return skipped


class UsingGotoRule(DiagnosticRuntimeRule):
    code = "BSL027"

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        root = getattr(context.tree, "root_node", None)
        if root is None:
            return []
        storage = DiagnosticStorage(context.path)
        for node in _ts_walk(root):
            if getattr(node, "type", None) != "goto_statement":
                continue
            _add_node_range(
                storage,
                code=self.code,
                message='Оператор "Перейти" не должен использоваться',
                severity=Severity.WARNING,
                lines=context.lines,
                start_node=node,
                end_node=self._goto_target_node(node),
            )
        return storage.diagnostics

    @staticmethod
    def _goto_target_node(goto_statement: Any) -> Any:
        children = _ts_children(goto_statement)
        for child in reversed(children):
            if getattr(child, "type", None) not in {";", "line_comment", "comment"}:
                return child
        return goto_statement


class DoubleNegativesRule(DiagnosticRuntimeRule):
    code = "BSL060"

    @staticmethod
    def _operator(node: Any) -> Any | None:
        return next((child for child in _ts_children(node) if child.type == "operator"), None)

    @classmethod
    def _operator_text(cls, node: Any) -> str:
        operator = cls._operator(node)
        return _ts_node_text(operator).casefold().strip() if operator is not None else ""

    @classmethod
    def _is_not_unary(cls, node: Any) -> bool:
        return getattr(node, "type", None) == "unary_expression" and cls._operator_text(node) in {
            "не",
            "not",
        }

    @classmethod
    def _expression_child(cls, node: Any) -> Any | None:
        return next((child for child in _ts_children(node) if child.type == "expression"), None)

    @classmethod
    def _single_expression_term(cls, expr: Any) -> Any | None:
        if getattr(expr, "type", None) != "expression":
            return None
        terms = [child for child in _ts_children(expr) if child.type != ";"]
        return terms[0] if len(terms) == 1 else None

    @classmethod
    def _text_starts_with_not_paren(cls, node: Any) -> bool:
        text = _ts_node_text(node).casefold().lstrip()
        return text.startswith("не (") or text.startswith("not (")

    @classmethod
    def _parent_binary_operator(cls, node: Any) -> str:
        current = node
        while getattr(current, "parent", None) is not None:
            current = current.parent
            if getattr(current, "type", None) == "binary_expression":
                return cls._operator_text(current)
            if getattr(current, "type", None) != "expression":
                return ""
        return ""

    @classmethod
    def _is_nested_in_logical_expression(cls, node: Any) -> bool:
        return cls._parent_binary_operator(node) in {"и", "and", "или", "or"}

    @classmethod
    def _binary_parts(cls, node: Any) -> tuple[Any, Any, Any] | None:
        children = _ts_children(node)
        for idx, child in enumerate(children):
            if getattr(child, "type", None) != "operator":
                continue
            if _ts_node_text(child).strip() != "<>":
                return None
            if idx == 0 or idx + 1 >= len(children):
                return None
            return children[idx - 1], child, children[idx + 1]
        return None

    @classmethod
    def _binary_diagnostic_nodes(cls, node: Any) -> tuple[Any, Any] | None:
        parts = cls._binary_parts(node)
        if parts is None:
            return None
        left, _operator, right = parts
        left_unary = cls._single_expression_term(left)
        if not cls._is_not_unary(left_unary):
            return None
        if cls._is_nested_in_logical_expression(node) and cls._text_starts_with_not_paren(node):
            return None
        start = cls._operator(left_unary)
        if start is None:
            return None
        return start, right

    @classmethod
    def _nested_unary_diagnostic_nodes(cls, node: Any) -> tuple[Any, Any] | None:
        if not cls._is_not_unary(node):
            return None
        if cls._parent_binary_operator(node):
            return None
        expr = cls._expression_child(node)
        inner = cls._single_expression_term(expr)
        if not cls._is_not_unary(inner):
            return None
        start = cls._operator(node)
        operand = cls._expression_child(inner)
        if start is None or operand is None:
            return None
        return start, operand

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        root = getattr(getattr(context, "tree", None), "root_node", None)
        if root is None:
            return []
        storage = DiagnosticStorage(context.path)
        seen: set[tuple[int, int, int, int]] = set()

        def add(start: Any, end: Any) -> None:
            key = (
                int(start.start_point[0]),
                _point_char(context.lines, start.start_point),
                int(end.end_point[0]),
                _point_char(context.lines, end.end_point),
            )
            if key in seen:
                return
            seen.add(key)
            _add_node_range(
                storage,
                code=self.code,
                message=_BSL060_MESSAGE,
                severity=Severity.WARNING,
                lines=context.lines,
                start_node=start,
                end_node=end,
            )

        if context.ts_nodes_for_types is not None:
            nodes_by_type = context.ts_nodes_for_types(
                context.tree,
                {"binary_expression", "unary_expression"},
            )
            binary_nodes = nodes_by_type["binary_expression"]
            unary_nodes = nodes_by_type["unary_expression"]
        else:
            walked_nodes = list(_ts_walk(root))
            binary_nodes = [
                node for node in walked_nodes if getattr(node, "type", None) == "binary_expression"
            ]
            unary_nodes = [
                node for node in walked_nodes if getattr(node, "type", None) == "unary_expression"
            ]

        for node in binary_nodes:
            nodes = self._binary_diagnostic_nodes(node)
            if nodes is not None:
                add(*nodes)
        for node in unary_nodes:
            nodes = self._nested_unary_diagnostic_nodes(node)
            if nodes is not None:
                add(*nodes)
        return storage.diagnostics


class DeprecatedMessageRule(DiagnosticRuntimeRule):
    code = "BSL041"
    _message_re = re.compile(r"\b(?:Сообщить|Message)\s*\(", re.IGNORECASE)

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        for idx, line in enumerate(context.lines):
            if _line_comment(line):
                continue
            clean = _code_mask_without_strings_and_comments(line)
            match = self._message_re.search(clean)
            if match is None:
                continue
            if clean[: match.start()].rstrip().endswith("."):
                continue
            storage.add_match(
                code=self.code,
                line=idx,
                start=match.start(),
                end=max(match.start(), match.end() - 1),
                severity=Severity.INFORMATION,
                message='Не следует использовать устаревший метод "Сообщить"',
            )
        return storage.diagnostics


class UsingHardcodeNetworkAddressRule(DiagnosticRuntimeRule):
    code = "BSL005"

    @staticmethod
    def _string_context(line: str, start: int, end: int) -> str:
        left = max(line.rfind(",", 0, start), line.rfind("(", 0, start))
        right_candidates = [pos for pos in (line.find(",", end), line.find(")", end)) if pos >= 0]
        right = min(right_candidates) if right_candidates else len(line)
        return line[left + 1 : right]

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        for idx, line in enumerate(context.lines):
            if _line_comment(line) or _BSL005_LINE_EXCLUSION_RE.search(line):
                continue
            for string_match in _DOUBLE_QUOTED_STRING_RE.finditer(line):
                if _BSL005_PARAM_VERSION_RE.search(
                    self._string_context(line, string_match.start(), string_match.end())
                ):
                    continue
                content = string_match.group()[1:-1]
                if len(content) <= 2 or _BSL005_URL_RE.match(content):
                    continue
                network_match = _BSL005_NETWORK_ADDRESS_RE.search(content)
                if network_match is None:
                    continue
                first_value = network_match.group(0)
                dot_count = first_value.count(".")
                if dot_count > 0 and (
                    content.count(".") > 3 or _BSL005_ALPHABET_RE.search(first_value)
                ):
                    continue
                if _BSL005_POPULAR_VERSION_RE.search(content):
                    continue
                storage.add_range(
                    code=self.code,
                    line=idx,
                    character=string_match.start(),
                    end_line=idx,
                    end_character=string_match.end(),
                    severity=Severity.ERROR,
                    message="Используется хранение в коде ip-адреса",
                )
        return storage.diagnostics


class UsingHardcodePathRule(DiagnosticRuntimeRule):
    code = "BSL006"

    @staticmethod
    def _is_path(content: str) -> bool:
        if len(content) <= 2 or _BSL006_URL_RE.match(content):
            return False
        if content.startswith("\\\\"):
            return True
        if re.match(r"^[A-Za-z]:(?:[\\/]|//|$)", content):
            return True
        if content.startswith("~/") or content.startswith("~\\"):
            return True
        if re.match(r"^%[^%]+%(?:[\\/]|//)", content):
            return True
        return bool(_BSL006_UNIX_STD_ROOT_RE.match(content))

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        for idx, line in enumerate(context.lines):
            if _line_comment(line):
                continue
            for match in _DOUBLE_QUOTED_STRING_RE.finditer(line):
                if not self._is_path(match.group()[1:-1]):
                    continue
                storage.add_range(
                    code=self.code,
                    line=idx,
                    character=match.start(),
                    end_line=idx,
                    end_character=match.end(),
                    severity=Severity.ERROR,
                    message="Используется хранение в коде пути к файлу",
                )
        return storage.diagnostics


class UsingServiceTagRule(DiagnosticRuntimeRule):
    code = "BSL023"
    _service_tag_re = re.compile(
        r"//\s*("
        r"todo|fixme|!!|mrg|@|отладка|debug|для\s*отладки"
        r"|(?:\{\{|\}\})КОНСТРУКТОР_|(?:\{\{|\}\})MRG"
        r"|Вставить\s*содержимое\s*обработчика"
        r"|Paste\s*handler\s*content|Insert\s*handler\s*code"
        r"|Insert\s*handler\s*content|Insert\s*handler\s*contents"
        r")",
        re.IGNORECASE,
    )

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        for idx, line in enumerate(context.lines):
            comment_start = _comment_start_outside_string(line)
            if comment_start < 0:
                continue
            match = self._service_tag_re.search(line, comment_start)
            if match is None:
                continue
            storage.add_range(
                code=self.code,
                line=idx,
                character=match.start(),
                end_line=idx,
                end_character=len(line),
                severity=Severity.INFORMATION,
                message=f'Найден служебный тег "{match.group(0)}"',
            )
        return storage.diagnostics


class SpaceAtStartCommentRule(DiagnosticRuntimeRule):
    code = "BSL024"

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        for idx, line in enumerate(context.lines):
            comment_start = None
            if idx < len(context.comment_starts):
                comment_start = context.comment_starts[idx]
            col = bsl024_find_report_comment_col(line, comment_start, comment_start_known=True)
            if col is None:
                continue
            storage.add_range(
                code=self.code,
                line=idx,
                character=col,
                end_line=idx,
                end_character=len(line),
                severity=Severity.INFORMATION,
                message=(
                    "Между символами комментария '//' и самим текстом комментария "
                    "должен быть пробел."
                ),
            )
        return storage.diagnostics


class EmptyStatementRule(DiagnosticRuntimeRule):
    code = "BSL025"

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        if not _ts_tree_available(context.tree):
            return []
        return self._run_from_tree(context)

    def _run_from_tree(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        root = context.tree.root_node
        for node in _ts_walk(root):
            if not self._is_empty_statement_semicolon(node, context.lines):
                continue
            _add_node_range(
                storage,
                code=self.code,
                message='Удалите ";"',
                severity=Severity.HINT,
                lines=context.lines,
                start_node=node,
                end_node=node,
            )
        return storage.diagnostics

    @classmethod
    def _is_empty_statement_semicolon(cls, node: Any, lines: list[str]) -> bool:
        if getattr(node, "type", None) != ";":
            return False
        line_idx = int(getattr(node, "start_point", ([-1]))[0])
        end_line_idx = int(getattr(node, "end_point", ([-2]))[0])
        if line_idx != end_line_idx or line_idx < 0 or line_idx >= len(lines):
            return False
        line_text = lines[line_idx]
        col = int(getattr(node, "start_point", (0, 0))[1])
        line_bytes = line_text.encode("utf-8", errors="replace")
        if col > 0 and col <= len(line_bytes) and line_bytes[col - 1 : col] == b";":
            return True
        parent_type = getattr(getattr(node, "parent", None), "type", None)
        if parent_type not in {
            "source_file",
            "procedure_definition",
            "function_definition",
            "try_statement",
        }:
            return False
        if line_text.strip() == ";":
            return True
        if parent_type in {"procedure_definition", "function_definition"}:
            before = line_bytes[:col].decode("utf-8", errors="replace").rstrip()
            return before.endswith(")") or bool(
                re.search(r"\b(?:Экспорт|Export)$", before, re.IGNORECASE)
            )
        return False


class MissingCodeTryCatchRule(DiagnosticRuntimeRule):
    code = "BSL028"
    message = 'Конструкция "Попытка...Исключение...КонецПопытки" не содержит кода в исключении'

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        root = getattr(context.tree, "root_node", None)
        if root is None:
            return []
        storage = DiagnosticStorage(context.path)
        for try_statement in _ts_walk(root):
            if getattr(try_statement, "type", None) != "try_statement":
                continue
            except_keyword = self._except_keyword(try_statement)
            if except_keyword is None:
                continue
            if self._except_has_code(try_statement, except_keyword):
                continue
            _add_node_range(
                storage,
                code=self.code,
                message=self.message,
                severity=Severity.ERROR,
                lines=context.lines,
                start_node=except_keyword,
                end_node=except_keyword,
            )
        return storage.diagnostics

    @staticmethod
    def _except_keyword(try_statement: Any) -> Any | None:
        return next(
            (
                child
                for child in _ts_children(try_statement)
                if getattr(child, "type", None) == "EXCEPT_KEYWORD"
            ),
            None,
        )

    @staticmethod
    def _except_has_code(try_statement: Any, except_keyword: Any) -> bool:
        except_start = getattr(except_keyword, "end_byte", 0)
        for child in _ts_children(try_statement):
            child_type = getattr(child, "type", None)
            if getattr(child, "start_byte", 0) < except_start:
                continue
            if child_type in {"EXCEPT_KEYWORD", "ENDTRY_KEYWORD", ";", "line_comment", "comment"}:
                continue
            return True
        return False


class ConsecutiveEmptyLinesRule(DiagnosticRuntimeRule):
    code = "BSL055"

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        blank_flags = (
            context.snapshot.blank_line_flags
            if context.snapshot is not None and hasattr(context.snapshot, "blank_line_flags")
            else [line.strip() == "" for line in context.lines]
        )
        storage = DiagnosticStorage(context.path)
        blank_run = 0
        run_start = 0
        for idx, is_blank in enumerate(blank_flags):
            if is_blank:
                if blank_run == 0:
                    run_start = idx
                blank_run += 1
                continue
            if blank_run > 1:
                self._add_issue(storage, run_start, run_start + blank_run - 1)
            blank_run = 0
        if blank_run > 1:
            self._add_issue(storage, run_start, run_start + blank_run)
        if len(context.lines) >= 2 and blank_flags[-1] and not blank_flags[-2]:
            self._add_issue(storage, len(context.lines) - 1, len(context.lines))
        return storage.diagnostics

    @classmethod
    def _add_issue(cls, storage: DiagnosticStorage, start_line: int, end_line: int) -> None:
        storage.add_range(
            code=cls.code,
            line=start_line,
            character=0,
            end_line=end_line,
            end_character=0,
            severity=Severity.INFORMATION,
            message="Удалите лишние последовательные пустые строки",
        )


class NestedTernaryOperatorRule(DiagnosticRuntimeRule):
    code = "BSL039"

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        ternaries = _ternary_spans(context)
        flagged: dict[int, _TernarySpan] = {}
        for inner in ternaries:
            if any(outer.start < inner.start and inner.end <= outer.end for outer in ternaries):
                flagged[inner.start] = inner

        if_start_re = re.compile(r"^\s*(?:Если|If|ИначеЕсли|ElsIf|ElseIf)\b", re.IGNORECASE)
        then_re = re.compile(r"\b(?:Тогда|Then)\b", re.IGNORECASE)
        for idx, line in enumerate(context.lines):
            if not if_start_re.match(line):
                continue
            end_idx = idx
            while end_idx < len(context.lines) and not then_re.search(context.lines[end_idx]):
                end_idx += 1
            if end_idx >= len(context.lines):
                continue
            for ternary in ternaries:
                if idx <= ternary.line <= end_idx:
                    flagged[ternary.start] = ternary

        storage = DiagnosticStorage(context.path)
        for span in sorted(flagged.values(), key=lambda item: item.start):
            storage.add_range(
                code=self.code,
                line=span.line,
                character=span.col,
                end_line=span.end_line,
                end_character=span.end_col,
                severity=Severity.WARNING,
                message="Не рекомендуется использовать вложенный тернарный оператор",
            )
        return storage.diagnostics


class MagicNumberRule(DiagnosticRuntimeRule):
    code = "BSL029"
    _authorized_numbers = {"0", "1", "-1"}
    _container_types = {"структура", "structure", "фиксированнаяструктура", "fixedstructure"}
    _map_types = {"соответствие", "map"}
    _insert_methods = {"вставить", "insert"}

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        root = getattr(context.tree, "root_node", None)
        if getattr(root, "text", None) is None:
            return []
        storage = DiagnosticStorage(context.path)
        nodes = self._nodes_by_type(context)
        container_assignments = self._container_assignments(nodes["assignment_statement"])
        for number in nodes["number"]:
            value = _ts_node_text(number)
            signed_value = self._signed_value(number, value)
            if signed_value in self._authorized_numbers:
                continue
            if self._inside_single_quoted_literal(context.lines, number):
                continue
            if self._ancestor_of_type(number, {"string"}) is not None:
                continue
            if self._inside_index_access(number):
                continue
            if self._inside_default_parameter(number):
                continue
            if self._wrong_error_number(number):
                self._add_number(storage, context.lines, number, value)
                continue
            expression = self._expression_ancestor(number)
            if expression is None:
                continue
            if self._inside_structure_or_correspondence(expression, container_assignments):
                continue
            if self._inside_property_assignment(expression):
                continue
            if not self._wrong_expression(expression):
                continue
            self._add_number(storage, context.lines, number, value)
        return storage.diagnostics

    @staticmethod
    def _nodes_by_type(context: DiagnosticDocumentContext) -> dict[str, list[Any]]:
        wanted = {"assignment_statement", "number"}
        if context.ts_nodes_for_types:
            return context.ts_nodes_for_types(context.tree, wanted)
        grouped = {node_type: [] for node_type in wanted}
        for node in _ts_walk(context.tree.root_node):
            node_type = getattr(node, "type", None)
            if node_type in grouped:
                grouped[node_type].append(node)
        return grouped

    def _add_number(
        self, storage: DiagnosticStorage, lines: list[str], number: Any, value: str
    ) -> None:
        _add_node_range(
            storage,
            code=self.code,
            message=(
                "Создайте константу с понятным названием, "
                f'присвойте ей значение "{value}" и используйте '
                "эту константу вместо магического числа."
            ),
            severity=Severity.INFORMATION,
            lines=lines,
            start_node=number,
            end_node=number,
        )

    @classmethod
    def _signed_value(cls, number: Any, value: str) -> str:
        expression = getattr(number, "parent", None)
        unary = getattr(expression, "parent", None)
        if getattr(unary, "type", None) != "unary_expression":
            return value
        operator = next(
            (child for child in _ts_children(unary) if getattr(child, "type", None) == "operator"),
            None,
        )
        return f"-{value}" if operator is not None and _ts_node_text(operator) == "-" else value

    @staticmethod
    def _expression_ancestor(node: Any) -> Any | None:
        current = getattr(node, "parent", None)
        while current is not None:
            if getattr(current, "type", None) == "expression":
                return current
            current = getattr(current, "parent", None)
        return None

    @staticmethod
    def _inside_default_parameter(node: Any) -> bool:
        current = getattr(node, "parent", None)
        while current is not None:
            if getattr(current, "type", None) == "parameter":
                return True
            if getattr(current, "type", None) in {
                "procedure_definition",
                "function_definition",
                "assignment_statement",
                "call_statement",
                "if_statement",
            }:
                return False
            current = getattr(current, "parent", None)
        return False

    @staticmethod
    def _inside_index_access(node: Any) -> bool:
        index = MagicNumberRule._ancestor_of_type(node, {"index"})
        if index is None:
            return False
        return MagicNumberRule._index_is_simple_number(index)

    @staticmethod
    def _index_is_simple_number(index: Any) -> bool:
        children = [
            child
            for child in _ts_children(index)
            if getattr(child, "type", None) not in {"line_comment", "comment"}
        ]
        if len(children) == 1 and getattr(children[0], "type", None) == "const_expression":
            return any(
                getattr(child, "type", None) == "number" for child in _ts_children(children[0])
            )
        return False

    @classmethod
    def _wrong_expression(cls, expression: Any) -> bool:
        if cls._ancestor_of_type(expression, {"return_statement"}) is not None:
            return True
        if cls._argument_index(expression) is not None:
            return True
        if cls._ancestor_of_type(expression, {"binary_expression"}) is not None:
            return True
        return cls._meaningful_expression_child_count(expression) > 1 or cls._has_binary_parent(
            expression
        )

    @staticmethod
    def _meaningful_expression_child_count(expression: Any) -> int:
        return sum(
            1
            for child in _ts_children(expression)
            if getattr(child, "type", None) not in {";", "line_comment", "comment"}
        )

    @staticmethod
    def _has_binary_parent(expression: Any) -> bool:
        parent = getattr(expression, "parent", None)
        return getattr(parent, "type", None) == "expression" and any(
            getattr(child, "type", None) == "operator" for child in _ts_children(parent)
        )

    @classmethod
    def _inside_structure_or_correspondence(
        cls,
        expression: Any,
        container_assignments: dict[str, list[tuple[str, Any]]],
    ) -> bool:
        if cls._inside_structure_constructor(expression):
            return True
        call_expression = cls._call_expression_for_argument(expression)
        if call_expression is None:
            return False
        method_name = cls._method_name(call_expression)
        if method_name not in cls._insert_methods:
            return False
        receiver = cls._call_receiver(call_expression)
        if receiver is None:
            return False
        container = cls._visible_container_assignment(
            container_assignments.get(receiver.casefold(), []), call_expression
        )
        if container is None:
            return False
        container_type, _assignment = container
        arg_index = cls._argument_index(expression)
        if container_type in cls._map_types:
            return arg_index in {0, 1} and cls._argument_is_simple_number(expression)
        return arg_index == 1 and cls._argument_is_simple_number(expression)

    @classmethod
    def _inside_structure_constructor(cls, expression: Any) -> bool:
        parent = getattr(expression, "parent", None)
        if getattr(parent, "type", None) != "arguments":
            return False
        new_expression = getattr(parent, "parent", None)
        if getattr(new_expression, "type", None) != "new_expression":
            return False
        type_name = cls._new_expression_type(new_expression)
        if type_name not in cls._container_types:
            return False
        arg_index = cls._argument_index(expression)
        if arg_index is None:
            return False
        if arg_index == 0 and type_name not in {"соответствие", "map"}:
            return False
        return cls._argument_is_simple_number(expression)

    @classmethod
    def _inside_property_assignment(cls, expression: Any) -> bool:
        assignment = cls._ancestor_of_type(expression, {"assignment_statement"})
        if assignment is None:
            return False
        left = next(
            (
                child
                for child in _ts_children(assignment)
                if getattr(child, "type", None) not in {"=", ";"}
            ),
            None,
        )
        if getattr(left, "type", None) != "property_access":
            return False
        return any(getattr(child, "type", None) == "property" for child in _ts_children(left))

    @classmethod
    def _container_assignments(
        cls,
        assignment_nodes: list[Any],
    ) -> dict[str, list[tuple[str, Any]]]:
        assignments: dict[str, list[tuple[str, Any]]] = {}
        for node in assignment_nodes:
            children = _ts_children(node)
            identifier = next(
                (child for child in children if getattr(child, "type", None) == "identifier"),
                None,
            )
            new_expression = next(
                (
                    child
                    for child in _ts_walk(node)
                    if getattr(child, "type", None) == "new_expression"
                ),
                None,
            )
            if identifier is None or new_expression is None:
                continue
            type_name = cls._new_expression_type(new_expression)
            if type_name in cls._container_types or type_name in cls._map_types:
                assignments.setdefault(_ts_node_text(identifier).casefold(), []).append(
                    (type_name, node)
                )
        return assignments

    @staticmethod
    def _new_expression_type(new_expression: Any) -> str:
        identifier = next(
            (
                child
                for child in _ts_children(new_expression)
                if getattr(child, "type", None) == "identifier"
            ),
            None,
        )
        return _ts_node_text(identifier).casefold() if identifier is not None else ""

    @staticmethod
    def _argument_index(expression: Any) -> int | None:
        parent = getattr(expression, "parent", None)
        if getattr(parent, "type", None) != "arguments":
            return None
        expressions = [
            child for child in _ts_children(parent) if getattr(child, "type", None) == "expression"
        ]
        try:
            return expressions.index(expression)
        except ValueError:
            return None

    @classmethod
    def _argument_is_simple_number(cls, expression: Any) -> bool:
        children = [
            child
            for child in _ts_children(expression)
            if getattr(child, "type", None) not in {";", "line_comment", "comment"}
        ]
        if len(children) != 1 or getattr(children[0], "type", None) != "const_expression":
            return False
        return any(getattr(child, "type", None) == "number" for child in _ts_children(children[0]))

    @staticmethod
    def _call_expression_for_argument(expression: Any) -> Any | None:
        args = getattr(expression, "parent", None)
        method_call = getattr(args, "parent", None)
        if (
            getattr(args, "type", None) != "arguments"
            or getattr(method_call, "type", None) != "method_call"
        ):
            return None
        call_expression = getattr(method_call, "parent", None)
        return (
            call_expression if getattr(call_expression, "type", None) == "call_expression" else None
        )

    @staticmethod
    def _method_name(call_expression: Any) -> str:
        method_call = next(
            (
                child
                for child in _ts_children(call_expression)
                if getattr(child, "type", None) == "method_call"
            ),
            None,
        )
        if method_call is None:
            return ""
        identifier = next(
            (
                child
                for child in _ts_children(method_call)
                if getattr(child, "type", None) == "identifier"
            ),
            None,
        )
        return _ts_node_text(identifier).casefold() if identifier is not None else ""

    @staticmethod
    def _call_receiver(call_expression: Any) -> str | None:
        access = next(
            (
                child
                for child in _ts_children(call_expression)
                if getattr(child, "type", None) == "access"
            ),
            None,
        )
        if access is None:
            return None
        identifier = next(
            (
                child
                for child in _ts_children(access)
                if getattr(child, "type", None) == "identifier"
            ),
            None,
        )
        return _ts_node_text(identifier) if identifier is not None else None

    @classmethod
    def _visible_container_assignment(
        cls, assignments: list[tuple[str, Any]], call_expression: Any
    ) -> tuple[str, Any] | None:
        call_statement = cls._ancestor_of_type(call_expression, {"call_statement"})
        if call_statement is None:
            return None
        call_owner = getattr(call_statement, "parent", None)
        visible: list[tuple[str, Any]] = []
        for type_name, assignment in assignments:
            assignment_owner = getattr(assignment, "parent", None)
            if not cls._same_node_span(call_owner, assignment_owner):
                continue
            if getattr(assignment, "start_byte", 0) >= getattr(call_expression, "start_byte", 0):
                continue
            visible.append((type_name, assignment))
        if not visible:
            return None
        return max(visible, key=lambda item: getattr(item[1], "start_byte", 0))

    @staticmethod
    def _same_node_span(left: Any, right: Any) -> bool:
        return (
            left is not None
            and right is not None
            and getattr(left, "type", None) == getattr(right, "type", None)
            and getattr(left, "start_byte", None) == getattr(right, "start_byte", None)
            and getattr(left, "end_byte", None) == getattr(right, "end_byte", None)
        )

    @staticmethod
    def _wrong_error_number(number: Any) -> bool:
        parent = getattr(number, "parent", None)
        if getattr(parent, "type", None) != "ERROR":
            return False
        if MagicNumberRule._ancestor_of_type(number, {"ternary_expression"}) is not None:
            return True
        error_text = _ts_node_text(parent).strip()
        if error_text.startswith(",") and ")" in error_text:
            return True
        children = _ts_children(parent)
        try:
            index = children.index(number)
        except ValueError:
            return False
        previous_types = [getattr(child, "type", None) for child in children[:index]]
        next_types = [
            getattr(child, "type", None)
            for child in children[index + 1 :]
            if getattr(child, "type", None) not in {".", "identifier"}
        ]
        return "TO_KEYWORD" in previous_types and bool(next_types) and next_types[0] == "operator"

    @staticmethod
    def _inside_single_quoted_literal(lines: list[str], number: Any) -> bool:
        line_idx = int(number.start_point[0])
        col = int(number.start_point[1])
        if line_idx < 0 or line_idx >= len(lines):
            return False
        line = lines[line_idx].encode("utf-8", errors="replace")
        left = line.rfind(b"'", 0, col + 1)
        if left < 0:
            return False
        right = line.find(b"'", col)
        return right >= 0

    @staticmethod
    def _ancestor_of_type(node: Any, types: set[str]) -> Any | None:
        current = getattr(node, "parent", None)
        while current is not None:
            if getattr(current, "type", None) in types:
                return current
            current = getattr(current, "parent", None)
        return None


class MagicDateRule(DiagnosticRuntimeRule):
    code = "BSL047"
    _authorized = {"00010101", "00010101000000", "000101010000"}
    _date_literal_re = re.compile(r"'([0-9][^']*[0-9])'")
    _string_literal_re = re.compile(r'"([0-9]{8}|[0-9]{14})"')

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        for idx, line in enumerate(context.lines):
            if line.lstrip().startswith("//"):
                continue
            code_part = line.split("//", 1)[0]
            for regex, is_string in (
                (self._date_literal_re, False),
                (self._string_literal_re, True),
            ):
                for match in regex.finditer(code_part):
                    value = match.group(1)
                    if self._line_prefix_skips(line, match.start(), match.end(), value, is_string):
                        continue
                    storage.add_match(
                        code=self.code,
                        line=idx,
                        start=match.start(),
                        end=match.end(),
                        severity=Severity.INFORMATION,
                        message=(
                            "Создайте переменную с понятным названием, присвойте ей "
                            f'значение "{match.group(0)}" и используйте эту константу '
                            "вместо магической даты."
                        ),
                    )
        return storage.diagnostics

    @classmethod
    def _valid_date(cls, value: str) -> bool:
        try:
            year = int(value[:4].lstrip("0") or "0")
            month = int(value[4:6])
            day = int(value[6:8])
        except ValueError:
            return False
        if year < 1 or year > 9999 or month < 1 or month > 12 or day < 1 or day > 31:
            return False
        if len(value) == 8:
            return True
        try:
            hour = int(value[8:10])
            minute = int(value[10:12])
            second = int(value[12:14])
        except ValueError:
            return False
        return hour <= 24 and minute <= 60 and second <= 60

    @classmethod
    def _line_prefix_skips(
        cls, line: str, start: int, end: int, value: str, is_string: bool
    ) -> bool:
        prefix = line[:start]
        code = line.split("//", 1)[0]
        if value in cls._authorized:
            return True
        digits = re.sub(r"\D", "", value)
        if digits in cls._authorized:
            return True
        if not is_string and len(digits) not in (8, 14):
            return True
        if re.search(r"\b(?:Возврат|Return)\b", prefix, re.IGNORECASE):
            return True
        suffix = code[end:].strip()
        if re.match(r"^\s*[\wА-Яа-яЁё.]+\s*=\s*$", prefix, re.IGNORECASE) and (
            suffix.startswith(",") or suffix.startswith(")")
        ):
            return True
        if re.match(r"^\s*[\wА-Яа-яЁё.]+\s*=\s*$", prefix, re.IGNORECASE) and suffix in {"", ";"}:
            return True
        if re.search(r"\b(?:Функция|Function|Процедура|Procedure)\b", prefix, re.IGNORECASE):
            return True
        if re.match(r"^\s*Структура\w*\.[\wА-Яа-яЁё]+\s*=\s*$", prefix, re.IGNORECASE):
            return True
        if re.search(r"\b(?:ФиксированнаяСтруктура|FixedStructure)\s*\(", line, re.IGNORECASE):
            return True
        if re.search(
            r"\b(?:Новый\s+)?(?:Структура|Structure|Соответствие|Map)\b", line, re.IGNORECASE
        ):
            return True
        if re.search(r"\.(?:Вставить|Insert)\s*\(", prefix, re.IGNORECASE):
            return True
        if is_string and not cls._valid_date(value):
            return True
        if re.match(r"^\s*[\wА-Яа-яЁё.]+\s*=\s*$", prefix, re.IGNORECASE):
            suffix = line[start + len(value) + 2 :].split("//", 1)[0].strip()
            if suffix.startswith(";") or suffix == "":
                return True
        if re.match(
            r"^\s*[\wА-Яа-яЁё.]+\s*=\s*(?:Дата|Date)\s*\(\s*$",
            prefix,
            re.IGNORECASE,
        ):
            suffix = code[start + len(value) + 2 :].strip()
            if suffix.startswith(")"):
                tail = suffix[1:].strip()
                if tail.startswith(";") or tail == "":
                    return True
        return False


class UselessTernaryOperatorRule(DiagnosticRuntimeRule):
    code = "BSL265"
    _boolean_operand_re = re.compile(
        r"^\s*(?:Истина|True|Ложь|False)\s*$", re.IGNORECASE | re.UNICODE
    )
    _simple_member_re = re.compile(r"^\s*[\wА-Яа-яЁё]+(?:\.[\wА-Яа-яЁё]+)+\s*$", re.UNICODE)
    _boolean_expr_re = re.compile(
        r"(<>\s*0|=\s*(?:Истина|True|Ложь|False)\b|"
        r"\b(?:И|And|ИЛИ|Or|НЕ|Not)\b|"
        r"(?:^|\.)\s*(?:Имеется|Имеются|Есть|Заполнено|Пустая|Пустой|Is|Has)\w*\s*\()",
        re.IGNORECASE | re.UNICODE,
    )
    _comment_re = re.compile(r"^\s*//")

    @classmethod
    def _is_boolean_operand(cls, text: str) -> bool:
        return bool(cls._boolean_operand_re.match(text))

    @classmethod
    def _is_boolean_expression(cls, text: str) -> bool:
        return bool(cls._boolean_expr_re.search(text))

    @classmethod
    def _is_simple_member_access(cls, text: str) -> bool:
        return bool(cls._simple_member_re.match(text))

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        for span in _ternary_spans(context):
            line_text = context.lines[span.line] if span.line < len(context.lines) else ""
            if self._comment_re.match(line_text):
                continue
            ternary_text = context.content[span.start : span.end]
            open_pos = ternary_text.find("(")
            close_pos = ternary_text.rfind(")")
            if open_pos < 0 or close_pos <= open_pos:
                continue
            parts = _split_top_level_args(ternary_text[open_pos + 1 : close_pos])
            if len(parts) < 3:
                continue
            condition_is_bool = self._is_boolean_operand(parts[0])
            then_is_bool = self._is_boolean_operand(parts[1])
            else_is_bool = self._is_boolean_operand(parts[2])
            both_branches_bool = then_is_bool and else_is_bool
            one_boolean_branch_with_boolean_value = (
                then_is_bool
                and (
                    self._is_boolean_expression(parts[2])
                    or (
                        self._is_simple_member_access(parts[0])
                        and self._is_simple_member_access(parts[2])
                    )
                )
            ) or (else_is_bool and self._is_boolean_expression(parts[1]))
            if condition_is_bool or both_branches_bool or one_boolean_branch_with_boolean_value:
                storage.add_range(
                    code=self.code,
                    line=span.line,
                    character=span.col,
                    end_line=span.end_line,
                    end_character=span.end_col,
                    severity=Severity.INFORMATION,
                    message="Бесполезный тернарный оператор",
                )
        return storage.diagnostics


class DeprecatedFindRule(DiagnosticRuntimeRule):
    code = "BSL066"
    _names = frozenset({"найти", "find"})
    _message = 'Используйте "СтрНайти" вместо устаревшего "Найти"'

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        root = getattr(context.tree, "root_node", None)
        if root is None:
            return []
        storage = DiagnosticStorage(context.path)
        for call in self._global_method_calls(context):
            if call["name"].casefold() not in self._names:
                continue
            ident = _diag._ts_child_of_type(call["node"], "identifier")
            if ident is None:
                continue
            _add_node_range(
                storage,
                code=self.code,
                message=self._message,
                severity=Severity.INFORMATION,
                lines=context.lines,
                start_node=ident,
                end_node=ident,
            )
        return storage.diagnostics

    @staticmethod
    def _global_method_calls(context: DiagnosticDocumentContext) -> list[dict[str, Any]]:
        if context.ts_nodes_for_types and context.global_method_calls_from_nodes:
            nodes = context.ts_nodes_for_types(context.tree, {"method_call"})
            return context.global_method_calls_from_nodes(nodes["method_call"], context.lines)
        return _diag._ts_global_method_calls(context.tree.root_node, context.lines)


class DeprecatedMethods8317Rule(DiagnosticRuntimeRule):
    code = "BSL178"

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        if not _bsl178_applicable_for_path(context.path):
            return []
        storage = DiagnosticStorage(context.path)
        for idx, line in enumerate(context.lines):
            if _line_comment(line):
                continue
            clean = _code_mask_without_strings_and_comments(line)
            for match in _BSL178_DEPRECATED_METHOD_RE.finditer(clean):
                method_name = match.group(1)
                storage.add_range(
                    code=self.code,
                    line=idx,
                    character=match.start(1),
                    end_line=idx,
                    end_character=match.end(1),
                    severity=Severity.INFORMATION,
                    message=(
                        f'Метод "{method_name}" устарел. Следует использовать одноименный '
                        "метод объекта типа МенеджерОбработкиОшибок"
                    ),
                )
        return storage.diagnostics


class DeprecatedMethods8310Rule(DiagnosticRuntimeRule):
    code = "BSL177"

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        for idx, line in enumerate(context.lines):
            if _line_comment(line):
                continue
            clean = _code_mask_without_strings_and_comments(line)
            for match in _BSL177_DEPRECATED_METHOD_RE.finditer(clean):
                method_name = match.group(1)
                replacement = _BSL177_METHOD_REPLACEMENTS.get(method_name.casefold(), "")
                storage.add_range(
                    code=self.code,
                    line=idx,
                    character=match.start(1),
                    end_line=idx,
                    end_character=_single_line_call_end(clean, match.end() - 1),
                    severity=Severity.INFORMATION,
                    message=f'Метод "{method_name}" устарел. Следует использовать "{replacement}".',
                )
        return storage.diagnostics


class GetFormMethodRule(DiagnosticRuntimeRule):
    code = "BSL195"

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        for idx, line in enumerate(context.lines):
            if _line_comment(line):
                continue
            clean = _code_mask_without_strings_and_comments(line)
            for match in _BSL195_GET_FORM_RE.finditer(clean):
                storage.add_range(
                    code=self.code,
                    line=idx,
                    character=match.start(1),
                    end_line=idx,
                    end_character=match.end(1),
                    severity=Severity.ERROR,
                    message="Не рекомендуемое использование метода ПолучитьФорму",
                )
        return storage.diagnostics


class DeprecatedTypeManagedFormRule(DiagnosticRuntimeRule):
    code = "BSL179"

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        for idx, line in enumerate(context.lines):
            if _line_comment(line):
                continue
            comment_pos = _comment_start_outside_string(line)
            clean = line if comment_pos < 0 else line[:comment_pos]
            for match in _BSL179_MANAGED_FORM_RE.finditer(clean):
                storage.add_range(
                    code=self.code,
                    line=idx,
                    character=match.start(1),
                    end_line=idx,
                    end_character=match.end(1),
                    severity=Severity.INFORMATION,
                    message='Замените устаревшее использование типа "УправляемаяФорма"',
                )
        return storage.diagnostics


class DisableSafeModeRule(DiagnosticRuntimeRule):
    code = "BSL180"

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        for idx, line in enumerate(context.lines):
            if _line_comment(line):
                continue
            clean = _code_mask_without_strings_and_comments(line)
            for match in _BSL180_DISABLE_SAFE_MODE_RE.finditer(clean):
                method_name = match.group(1)
                arg = match.group(2).strip().casefold()
                if method_name.casefold() in {"установитьбезопасныйрежим", "setsafemode"}:
                    if arg in {"истина", "true"}:
                        continue
                elif arg in {"ложь", "false"}:
                    continue
                storage.add_range(
                    code=self.code,
                    line=idx,
                    character=match.start(1),
                    end_line=idx,
                    end_character=match.end(1),
                    severity=Severity.ERROR,
                    message="Проверьте отключение безопасного режима",
                )
        return storage.diagnostics


class ExternalAppStartingRule(DiagnosticRuntimeRule):
    code = "BSL185"

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        for idx, line in enumerate(context.lines):
            if _line_comment(line):
                continue
            clean = _code_mask_without_strings_and_comments(line)
            for match in _BSL185_EXTERNAL_APP_RE.finditer(clean):
                storage.add_range(
                    code=self.code,
                    line=idx,
                    character=match.start(1),
                    end_line=idx,
                    end_character=match.end(1),
                    severity=Severity.ERROR,
                    message="Проверьте запуск внешнего приложения",
                )
        return storage.diagnostics


class FileSystemAccessRule(DiagnosticRuntimeRule):
    code = "BSL188"
    message = "Проверьте обращение к файловой системе"
    severity = Severity.WARNING
    new_type_names = _BSL188_FILESYSTEM_NEW_NAMES
    global_method_names = _BSL188_FILESYSTEM_METHOD_NAMES

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        if not self._tree_ok(context):
            return []
        storage = DiagnosticStorage(context.path)
        for node in self._new_expression_nodes(context):
            if self._new_expression_type_name(node) not in self.new_type_names:
                continue
            self._add_node_diag(storage, context, node)
        for node in self._dynamic_new_expression_nodes(context):
            if self._dynamic_new_type_name(node) not in self.new_type_names:
                continue
            self._add_node_diag(storage, context, node)
        if self.global_method_names:
            for call in self._global_method_calls(context):
                if call["name"].casefold() not in self.global_method_names:
                    continue
                storage.add_range(
                    code=self.code,
                    line=int(call["line"]),
                    character=int(call["character"]),
                    end_line=int(call["line"]),
                    end_character=int(call["end_character"]),
                    severity=self.severity,
                    message=self.message,
                )
        return storage.diagnostics

    @staticmethod
    def _tree_ok(context: DiagnosticDocumentContext) -> bool:
        root = getattr(context.tree, "root_node", None)
        return root is not None and isinstance(getattr(root, "text", None), (bytes, bytearray))

    @staticmethod
    def _new_expression_nodes(context: DiagnosticDocumentContext) -> list[Any]:
        if context.ts_nodes_for_types:
            return context.ts_nodes_for_types(context.tree, {"new_expression"})["new_expression"]
        return [
            node
            for node in _ts_walk(context.tree.root_node)
            if getattr(node, "type", None) == "new_expression"
        ]

    @staticmethod
    def _new_expression_type_name(node: Any) -> str:
        identifier = next(
            (child for child in _ts_children(node) if getattr(child, "type", None) == "identifier"),
            None,
        )
        return _ts_node_text(identifier).casefold() if identifier is not None else ""

    @staticmethod
    def _dynamic_new_expression_nodes(context: DiagnosticDocumentContext) -> list[Any]:
        if context.ts_nodes_for_types:
            nodes = context.ts_nodes_for_types(context.tree, {"new_expression_method"})[
                "new_expression_method"
            ]
        else:
            nodes = [
                node
                for node in _ts_walk(context.tree.root_node)
                if getattr(node, "type", None) == "new_expression_method"
            ]
        return [node for node in nodes if FileSystemAccessRule._dynamic_new_type_name(node)]

    @staticmethod
    def _dynamic_new_type_name(node: Any) -> str:
        string_child = next(
            (child for child in _ts_walk(node) if getattr(child, "type", None) == "string"),
            None,
        )
        if string_child is None:
            return ""
        literal = _ts_node_text(string_child).strip()
        if len(literal) < 2 or not literal.startswith('"') or not literal.endswith('"'):
            return ""
        return literal[1:-1].replace('""', '"').casefold()

    @staticmethod
    def _global_method_calls(context: DiagnosticDocumentContext) -> list[dict[str, Any]]:
        if context.ts_nodes_for_types:
            nodes = context.ts_nodes_for_types(context.tree, {"method_call"})
            method_call_nodes = nodes["method_call"]
        else:
            method_call_nodes = [
                node
                for node in _ts_walk(context.tree.root_node)
                if getattr(node, "type", None) == "method_call"
            ]
        out: list[dict[str, Any]] = []
        for node in method_call_nodes:
            parent_type = getattr(getattr(node, "parent", None), "type", None)
            if parent_type not in {"expression", "call_statement"}:
                continue
            ident = next(
                (
                    child
                    for child in _ts_children(node)
                    if getattr(child, "type", None) == "identifier"
                ),
                None,
            )
            if ident is None:
                continue
            start = ident.start_point
            end = ident.end_point
            out.append(
                {
                    "node": node,
                    "name": _ts_node_text(ident),
                    "line": int(start[0]),
                    "character": _point_char(context.lines, start),
                    "end_character": _point_char(context.lines, end),
                }
            )
        return out

    def _add_node_diag(
        self,
        storage: DiagnosticStorage,
        context: DiagnosticDocumentContext,
        node: Any,
    ) -> None:
        _add_node_range(
            storage,
            code=self.code,
            message=self.message,
            severity=self.severity,
            lines=context.lines,
            start_node=node,
            end_node=node,
        )


class InternetAccessRule(FileSystemAccessRule):
    code = "BSL203"
    message = "Проверьте обращение к Интернет-ресурсам"
    severity = Severity.WARNING
    new_type_names = _BSL203_INTERNET_NEW_NAMES
    global_method_names = frozenset[str]()


class UseSystemInformationRule(FileSystemAccessRule):
    code = "BSL264"
    message = "Избавьтесь от использования объекта `СистемнаяИнформация`"
    severity = Severity.ERROR
    new_type_names = _BSL264_SYSTEM_INFO_NEW_NAMES
    global_method_names = frozenset[str]()


class IsInRoleMethodRule(DiagnosticRuntimeRule):
    code = "BSL205"

    @staticmethod
    def _has_privileged_var(expression: str, privileged_vars: set[str]) -> bool:
        return any(
            re.search(rf"(?<!\w){re.escape(var)}(?!\w)", expression) for var in privileged_vars
        )

    @staticmethod
    def _next_privileged_call_start(expression: str, start: int) -> int | None:
        match = _BSL205_PRIVILEGED_MODE_RE.search(expression, start)
        return None if match is None else match.start()

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        is_in_role_vars: set[str] = set()
        privileged_mode_vars: set[str] = set()

        for idx, line in enumerate(context.lines):
            if _line_comment(line):
                continue
            code_part = _code_before_comment(line)
            clean = _code_mask_without_strings_and_comments(line)

            assignment = _BSL205_ASSIGNMENT_RE.match(clean)
            if assignment is not None:
                assigned_name = assignment.group(1)
                is_in_role_vars.discard(assigned_name)
                privileged_mode_vars.discard(assigned_name)
                if _BSL205_ROLE_AVAILABLE_RE.search(clean) is not None:
                    is_in_role_vars.add(assigned_name)
                elif _BSL205_PRIVILEGED_MODE_RE.search(clean) is not None:
                    privileged_mode_vars.add(assigned_name)

            if_match = _BSL205_IF_RE.match(clean)
            if if_match is None:
                continue

            expression_start = if_match.start(1)
            expression = code_part[expression_start : if_match.end(1)]
            clean_expression = clean[expression_start : if_match.end(1)]
            has_privileged_var = self._has_privileged_var(clean_expression, privileged_mode_vars)

            for match in _BSL205_ROLE_AVAILABLE_RE.finditer(clean_expression):
                if has_privileged_var:
                    continue
                if self._next_privileged_call_start(clean_expression, match.end()) is not None:
                    continue
                open_paren = expression.find("(", match.start())
                storage.add_range(
                    code=self.code,
                    line=idx,
                    character=expression_start + match.start(1),
                    end_line=idx,
                    end_character=expression_start + _single_line_call_end(expression, open_paren),
                    severity=Severity.WARNING,
                    message="Для проверки прав доступа в коде следует использовать метод ПравоДоступа",
                )

            if has_privileged_var:
                continue
            for var in is_in_role_vars:
                for match in re.finditer(rf"(?<!\w){re.escape(var)}(?!\w)", clean_expression):
                    if self._next_privileged_call_start(clean_expression, match.end()) is not None:
                        continue
                    storage.add_range(
                        code=self.code,
                        line=idx,
                        character=expression_start + match.start(),
                        end_line=idx,
                        end_character=expression_start + match.end(),
                        severity=Severity.WARNING,
                        message="Для проверки прав доступа в коде следует использовать метод ПравоДоступа",
                    )
        return storage.diagnostics


class ExecuteExternalCodeRule(DiagnosticRuntimeRule):
    code = "BSL183"

    @staticmethod
    def _client_only_method(lines: list[str], start_idx: int) -> bool:
        idx = start_idx - 1
        while idx >= 0:
            stripped = lines[idx].strip()
            if not stripped or stripped.startswith("//"):
                idx -= 1
                continue
            if not stripped.startswith("&"):
                return False
            directive = stripped[1:].split()[0].casefold()
            if directive in {"наклиенте", "atclient"}:
                return True
            idx -= 1
        return False

    @staticmethod
    def _fallback_procs(lines: list[str]) -> list[Any]:
        proc_re = re.compile(
            r"^\s*(?:Процедура|Procedure|Функция|Function)\s+"
            r"([А-ЯЁа-яёA-Za-z_][А-ЯЁа-яёA-Za-z_0-9]*)",
            re.IGNORECASE | re.UNICODE,
        )
        end_re = re.compile(
            r"^\s*(?:КонецПроцедуры|EndProcedure|КонецФункции|EndFunction)\b", re.IGNORECASE
        )
        out: list[Any] = []
        idx = 0
        while idx < len(lines):
            match = proc_re.match(lines[idx])
            if match is None:
                idx += 1
                continue
            end_idx = idx
            scan = idx + 1
            while scan < len(lines):
                if end_re.match(lines[scan]):
                    end_idx = scan
                    break
                scan += 1
            out.append(
                type(
                    "ProcLike",
                    (),
                    {
                        "name": match.group(1),
                        "start_idx": idx,
                        "end_idx": end_idx,
                        "header_col": match.start(1),
                    },
                )()
            )
            idx = max(scan, idx + 1)
        return out

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        procs = (
            list(getattr(context.snapshot, "procs", []) or [])
            if context.snapshot is not None
            else self._fallback_procs(context.lines)
        )
        if not procs:
            procs = self._fallback_procs(context.lines)

        for proc in procs:
            if self._client_only_method(context.lines, int(proc.start_idx)):
                continue
            for idx in range(
                int(proc.start_idx) + 1, min(int(proc.end_idx) + 1, len(context.lines))
            ):
                clean = _code_mask_without_strings_and_comments(context.lines[idx])
                for match in _BSL183_EXECUTE_EXTERNAL_CODE_RE.finditer(clean):
                    open_paren = clean.find("(", match.start())
                    storage.add_range(
                        code=self.code,
                        line=idx,
                        character=match.start(1),
                        end_line=idx,
                        end_character=_single_line_call_end(clean, open_paren),
                        severity=Severity.ERROR,
                        message="Запрещено выполнение произвольного кода на сервере",
                    )
        return storage.diagnostics


class ExecuteExternalCodeInCommonModuleRule(DiagnosticRuntimeRule):
    code = "BSL184"

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        if not common_module_execute_external_code_applicable(context.path):
            return []

        storage = DiagnosticStorage(context.path)
        for idx, line in enumerate(context.lines):
            clean = _code_mask_without_strings_and_comments(line)
            for match in _BSL183_EXECUTE_EXTERNAL_CODE_RE.finditer(clean):
                open_paren = clean.find("(", match.start())
                storage.add_range(
                    code=self.code,
                    line=idx,
                    character=match.start(1),
                    end_line=idx,
                    end_character=_single_line_call_end(clean, open_paren),
                    severity=Severity.WARNING,
                    message=(
                        "Выполнение произвольного кода в общем модуле на сервере "
                        "является потенциальной уязвимостью"
                    ),
                )
        return storage.diagnostics


class OSUsersMethodRule(DiagnosticRuntimeRule):
    code = "BSL226"

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        for idx, line in enumerate(context.lines):
            clean = _code_mask_without_strings_and_comments(line)
            for match in _BSL226_OS_USERS_RE.finditer(clean):
                storage.add_range(
                    code=self.code,
                    line=idx,
                    character=match.start(1),
                    end_line=idx,
                    end_character=match.end(1),
                    severity=Severity.WARNING,
                    message="Проверить потенциально вредоносное использование метода ПользователиОС",
                )
        return storage.diagnostics


class SetPrivilegedModeRule(DiagnosticRuntimeRule):
    code = "BSL247"

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        for idx, line in enumerate(context.lines):
            clean = _code_mask_without_strings_and_comments(line)
            for match in _BSL247_SET_PRIVILEGED_RE.finditer(clean):
                arg = match.group(2).strip().casefold()
                if arg in {"ложь", "false"}:
                    continue
                storage.add_range(
                    code=self.code,
                    line=idx,
                    character=match.start(1),
                    end_line=idx,
                    end_character=match.end(1),
                    severity=Severity.WARNING,
                    message="Проверьте установку привилегированного режима",
                )
        return storage.diagnostics


class TempFilesDirRule(DiagnosticRuntimeRule):
    code = "BSL250"

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        for idx, line in enumerate(context.lines):
            clean = _code_mask_without_strings_and_comments(line)
            for match in _BSL250_TEMPFILES_RE.finditer(clean):
                storage.add_range(
                    code=self.code,
                    line=idx,
                    character=match.start(1),
                    end_line=idx,
                    end_character=match.end(1),
                    severity=Severity.WARNING,
                    message="Не рекомендуемый вызов функции КаталогВременныхФайлов()",
                )
        return storage.diagnostics


class UsingExternalCodeToolsRule(DiagnosticRuntimeRule):
    code = "BSL267"

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        for idx, line in enumerate(context.lines):
            code_part = _code_before_comment(line)
            clean = _code_mask_without_strings_and_comments(code_part)
            for match in _BSL267_EXTERNAL_CODE_TOOLS_RE.finditer(clean):
                open_paren = clean.find("(", match.start())
                end_line, end_character = _multi_line_call_end(context.lines, idx, open_paren)
                if end_line == idx:
                    end_character = _call_chain_end(clean, open_paren)
                storage.add_range(
                    code=self.code,
                    line=idx,
                    character=match.start(1),
                    end_line=end_line,
                    end_character=end_character,
                    severity=Severity.ERROR,
                    message="Запрещено использование возможности выполнения внешнего кода",
                )
        return storage.diagnostics


class UsingSynchronousCallsRule(DiagnosticRuntimeRule):
    code = "BSL272"

    @staticmethod
    def _server_only_method(lines: list[str], start_idx: int) -> bool:
        idx = start_idx - 1
        while idx >= 0:
            stripped = lines[idx].strip()
            if not stripped or stripped.startswith("//"):
                idx -= 1
                continue
            if not stripped.startswith("&"):
                return False
            directive = stripped[1:].split()[0].casefold()
            return directive in {
                "насервере",
                "atserver",
                "насерверебезконтекста",
                "atservernocontext",
            }
        return False

    @staticmethod
    def _server_only_lines(context: DiagnosticDocumentContext) -> set[int]:
        procs = (
            list(getattr(context.snapshot, "procs", []) or [])
            if context.snapshot is not None
            else ExecuteExternalCodeRule._fallback_procs(context.lines)
        )
        if not procs:
            procs = ExecuteExternalCodeRule._fallback_procs(context.lines)
        skipped: set[int] = set()
        for proc in procs:
            if UsingSynchronousCallsRule._server_only_method(context.lines, int(proc.start_idx)):
                skipped.update(
                    range(int(proc.start_idx), min(int(proc.end_idx) + 1, len(context.lines)))
                )
        return skipped

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        if _path_is_bsl272_server_only_module(context.path):
            return []
        storage = DiagnosticStorage(context.path)
        skipped_lines = self._server_only_lines(context)
        clean_lines = [
            _code_mask_without_strings_and_comments(_code_before_comment(line))
            for line in context.lines
        ]
        for idx, clean in enumerate(clean_lines):
            if idx in skipped_lines:
                continue
            for match in _BSL272_SYNC_RE.finditer(clean):
                method_name = context.lines[idx][match.start("name") : match.end("name")]
                replacement = _BSL272_SYNC_REPLACEMENTS.get(method_name.upper(), "")
                open_paren = clean.find("(", match.start("name"))
                end_line, end_character = _multi_line_call_end(clean_lines, idx, open_paren)
                storage.add_range(
                    code=self.code,
                    line=idx,
                    character=match.start("name"),
                    end_line=end_line,
                    end_character=end_character,
                    severity=Severity.WARNING,
                    message=(
                        f"Вместо синхронного метода `{method_name}` необходимо "
                        f"использовать `{replacement}`"
                    ),
                )
        return storage.diagnostics


class VirtualTableCallWithoutParametersRule(DiagnosticRuntimeRule):
    code = "BSL273"
    message = "Не следует использовать виртуальные таблицы без параметров"

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        for line_no, content_base, _content, head, _ended_query in self._content_lines(context):
            for match in _BSL273_VIRTUAL_TABLE_RE.finditer(head):
                open_match = match.group("open")
                if open_match is None:
                    storage.add_range(
                        code=self.code,
                        message=self.message,
                        severity=Severity.ERROR,
                        line=line_no - 1,
                        character=content_base + match.start("name"),
                        end_line=line_no - 1,
                        end_character=content_base + match.end("name"),
                    )
                    continue

                open_idx = match.end("open") - 1
                close_pos = _matching_paren(head, open_idx)
                if close_pos == len(head) and ")" not in head[open_idx + 1 :]:
                    continue
                close_idx = close_pos - 1
                if close_idx < open_idx:
                    continue
                args = head[open_idx + 1 : close_idx]
                parts = [part.strip() for part in _split_top_level_args(args)]
                if not parts or all(not part for part in parts):
                    violation = True
                elif len(parts) == 1:
                    violation = False
                else:
                    violation = all(not part for part in parts[1:])
                if violation:
                    storage.add_range(
                        code=self.code,
                        message=self.message,
                        severity=Severity.ERROR,
                        line=line_no - 1,
                        character=content_base + match.start("name"),
                        end_line=line_no - 1,
                        end_character=content_base + close_idx + 1,
                    )
        return storage.diagnostics

    @staticmethod
    def _content_lines(context: DiagnosticDocumentContext) -> list[tuple[int, int, str, str, bool]]:
        snapshot = context.snapshot
        if snapshot is not None:
            return [
                (line.line_no, line.content_base, line.content, line.head, line.ended_query)
                for block in snapshot.query_text_blocks
                for line in block.content_lines
            ]

        from onec_hbk_bsl.analysis import diagnostics as _diag

        return [
            content_line
            for start_idx, block_lines in _diag._iter_query_text_blocks(context.lines)
            for content_line in _diag._iter_query_text_content_lines(start_idx, block_lines)
        ]


class NumberOfValuesInStructureConstructorRule(DiagnosticRuntimeRule):
    code = "BSL225"
    message = "Уменьшите количество значений свойств, передаваемых в конструктор структуры"
    _type_names = {"структура", "structure", "фиксированнаяструктура", "fixedstructure"}
    _max_values_count = 3

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        root = getattr(getattr(context.tree, "root_node", None), "text", None)
        if not isinstance(root, (bytes, bytearray)):
            return []
        storage = DiagnosticStorage(context.path)
        for node in context.ts_nodes_for_types(context.tree, {"new_expression"})["new_expression"]:
            type_node = self._type_node(node)
            if type_node is None or _ts_node_text(type_node).casefold() not in self._type_names:
                continue
            args_node = next(
                (
                    child
                    for child in _ts_children(node)
                    if getattr(child, "type", None) == "arguments"
                ),
                None,
            )
            if args_node is None:
                continue
            if self._call_param_count(args_node) <= self._max_values_count + 1:
                continue
            _add_node_range(
                storage,
                code=self.code,
                message=self.message,
                severity=Severity.INFORMATION,
                lines=context.lines,
                start_node=node,
                end_node=node,
            )
        return storage.diagnostics

    @staticmethod
    def _type_node(node: Any) -> Any | None:
        for child in _ts_children(node):
            if getattr(child, "type", None) == "identifier":
                return child
        return None

    @staticmethod
    def _call_param_count(arguments_node: Any) -> int:
        meaningful = [
            child
            for child in _ts_children(arguments_node)
            if getattr(child, "type", None) not in {"(", ")", "line_comment", "comment"}
        ]
        if not meaningful:
            return 0
        separator_count = sum(
            1 for child in meaningful if getattr(child, "type", None) in {",", "omitted_argument"}
        )
        return separator_count + 1


class MissingTempStorageDeletionRule(DiagnosticRuntimeRule):
    code = "BSL217"
    message = (
        "Нужно добавить удаление данных из временного хранилища после использования, вызвав "
        '"УдалитьИзВременногоХранилища"'
    )
    _get_names = {"получитьизвременногохранилища", "getfromtempstorage"}
    _delete_names = {"удалитьизвременногохранилища", "deletefromtempstorage"}

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        root = getattr(context.tree, "root_node", None)
        if root is None:
            return []
        storage = DiagnosticStorage(context.path)
        calls = self._global_method_calls(context)
        for call in calls:
            if call["name"].casefold() not in self._get_names:
                continue
            arg_key = self._first_arg_key(call["node"])
            if arg_key is None:
                continue
            if self._has_later_delete(call, calls, arg_key):
                continue
            _add_node_range(
                storage,
                code=self.code,
                message=self.message,
                severity=Severity.WARNING,
                lines=context.lines,
                start_node=call["node"],
                end_node=call["node"],
            )
        return storage.diagnostics

    @classmethod
    def _global_method_calls(cls, context: DiagnosticDocumentContext) -> list[dict[str, Any]]:
        if context.ts_nodes_for_types and context.global_method_calls_from_nodes:
            nodes = context.ts_nodes_for_types(context.tree, {"method_call"})
            return context.global_method_calls_from_nodes(nodes["method_call"], context.lines)
        return _diag._ts_global_method_calls(context.tree.root_node, context.lines)

    @classmethod
    def _has_later_delete(
        cls, source_call: dict[str, Any], calls: list[dict[str, Any]], arg_key: str
    ) -> bool:
        source_scope = cls._scope_key(source_call["node"])
        source_line = int(source_call["line"])
        for candidate in calls:
            if int(candidate["line"]) <= source_line:
                continue
            if candidate["name"].casefold() not in cls._delete_names:
                continue
            if cls._scope_key(candidate["node"]) != source_scope:
                continue
            if cls._first_arg_key(candidate["node"]) == arg_key:
                return True
        return False

    @staticmethod
    def _first_arg_key(method_call: Any) -> str | None:
        args = _diag._ts_method_call_arg_exprs(method_call)
        if not args:
            return None
        return "".join(_ts_node_text(args[0]).split()).casefold()

    @staticmethod
    def _scope_key(node: Any) -> tuple[str, int, int] | None:
        current = getattr(node, "parent", None)
        while current is not None:
            node_type = getattr(current, "type", None)
            if node_type in {"procedure_definition", "function_definition"}:
                return (
                    node_type,
                    int(getattr(current, "start_byte", 0)),
                    int(getattr(current, "end_byte", 0)),
                )
            current = getattr(current, "parent", None)
        return None


class MissingTemporaryFileDeletionRule(DiagnosticRuntimeRule):
    code = "BSL218"
    message = "Нужно добавить удаление временного файла после использования"
    _get_temp_names = frozenset({"получитьимявременногофайла", "gettempfilename"})
    _delete_names = frozenset(
        {
            "удалитьфайлы",
            "deletefiles",
            "начатьудалениефайлов",
            "begindeletingfiles",
            "переместитьфайл",
            "movefile",
        }
    )
    _skip_routine_child_types = frozenset(
        {
            "PROCEDURE_KEYWORD",
            "FUNCTION_KEYWORD",
            "EXPORT_KEYWORD",
            "identifier",
            "parameters",
            "ENDPROCEDURE_KEYWORD",
            "ENDFUNCTION_KEYWORD",
        }
    )

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        root = getattr(getattr(context.tree, "root_node", None), "text", None)
        if not isinstance(root, (bytes, bytearray)):
            return []
        storage = DiagnosticStorage(context.path)
        global_calls = self._global_calls(context)
        for call in global_calls:
            if str(call["name"]).casefold() not in self._get_temp_names:
                continue
            call_node = call["node"]
            assignment = self._assignment_ancestor(call_node)
            if assignment is None:
                self._add_call(storage, context.lines, call_node)
                continue
            var_name = self._assignment_lvalue_text(assignment)
            block_parent = self._skip_error_ancestor(getattr(assignment, "parent", None))
            roots = self._code_block_roots(block_parent) if block_parent is not None else None
            if not var_name or not roots:
                self._add_call(storage, context.lines, call_node)
                continue
            if not self._has_deletion_after(roots, context.lines, int(call["line"]), var_name):
                self._add_call(storage, context.lines, call_node)
        return storage.diagnostics

    def _global_calls(self, context: DiagnosticDocumentContext) -> list[dict[str, Any]]:
        if context.ts_nodes_for_types and context.global_method_calls_from_nodes:
            nodes = context.ts_nodes_for_types(context.tree, {"method_call"})
            return context.global_method_calls_from_nodes(nodes["method_call"], context.lines)

        from onec_hbk_bsl.analysis import diagnostics as _diag

        return _diag._ts_global_method_calls(context.tree.root_node, context.lines)

    @staticmethod
    def _assignment_ancestor(node: Any) -> Any | None:
        current = node
        while current is not None:
            if getattr(current, "type", None) == "assignment_statement":
                return current
            current = getattr(current, "parent", None)
        return None

    @staticmethod
    def _skip_error_ancestor(node: Any) -> Any | None:
        current = node
        while current is not None and getattr(current, "type", None) == "ERROR":
            current = getattr(current, "parent", None)
        return current

    @staticmethod
    def _assignment_lvalue_text(assign: Any) -> str | None:
        parts: list[str] = []
        for child in _ts_children(assign):
            if getattr(child, "type", None) == "=":
                break
            parts.append(_ts_node_text(child))
        text = "".join(parts).strip()
        return text or None

    @classmethod
    def _code_block_roots(cls, node: Any) -> list[Any] | None:
        node_type = getattr(node, "type", None)
        children = _ts_children(node)
        if node_type in {"procedure_definition", "function_definition"}:
            return [
                child
                for child in children
                if getattr(child, "type", None) not in cls._skip_routine_child_types
            ]
        if node_type == "source_file":
            return [child for child in children if getattr(child, "type", None) != "preprocessor"]
        if node_type == "if_statement":
            return cls._roots_between(
                children, "THEN_KEYWORD", {"elseif_clause", "else_clause", "ENDIF_KEYWORD"}
            )
        if node_type == "elseif_clause":
            return cls._roots_after(children, "THEN_KEYWORD")
        if node_type == "else_clause":
            return cls._roots_after(children, "ELSE_KEYWORD")
        if node_type in {"while_statement", "for_statement", "for_each_statement"}:
            return cls._roots_between(children, "DO_KEYWORD", {"ENDDO_KEYWORD"})
        if node_type == "try_statement":
            return cls._roots_between(children, "TRY_KEYWORD", {"EXCEPT_KEYWORD", "ENDTRY_KEYWORD"})
        return None

    @staticmethod
    def _roots_between(
        children: list[Any],
        start_type: str,
        end_types: set[str],
    ) -> list[Any]:
        start_idx = next(
            (
                idx
                for idx, child in enumerate(children)
                if getattr(child, "type", None) == start_type
            ),
            None,
        )
        if start_idx is None:
            return []
        end_idx = next(
            (
                idx
                for idx in range(start_idx + 1, len(children))
                if getattr(children[idx], "type", None) in end_types
            ),
            len(children),
        )
        return children[start_idx + 1 : end_idx]

    @staticmethod
    def _roots_after(children: list[Any], keyword_type: str) -> list[Any]:
        keyword_idx = next(
            (
                idx
                for idx, child in enumerate(children)
                if getattr(child, "type", None) == keyword_type
            ),
            None,
        )
        if keyword_idx is None:
            return []
        return children[keyword_idx + 1 :]

    @classmethod
    def _has_deletion_after(
        cls,
        roots: list[Any],
        lines: list[str],
        after_line: int,
        var_name: str,
    ) -> bool:
        var_cf = var_name.casefold()
        for root in roots:
            for call in cls._global_calls_in_subtree(root, lines):
                if int(call["line"]) <= after_line:
                    continue
                if str(call["name"]).casefold() not in cls._delete_names:
                    continue
                for expr in cls._method_call_arg_exprs(call["node"]):
                    if _ts_node_text(expr).strip().casefold() == var_cf:
                        return True
        return False

    @staticmethod
    def _global_calls_in_subtree(node: Any, lines: list[str]) -> list[dict[str, Any]]:
        calls: list[dict[str, Any]] = []
        for child in _ts_walk(node):
            if getattr(child, "type", None) != "method_call":
                continue
            if getattr(getattr(child, "parent", None), "type", None) == "call_expression":
                continue
            ident = next(
                (
                    call_child
                    for call_child in _ts_children(child)
                    if getattr(call_child, "type", None) == "identifier"
                ),
                None,
            )
            if ident is None:
                continue
            calls.append(
                {
                    "node": child,
                    "name": _ts_node_text(ident),
                    "line": int(ident.start_point[0]) + 1,
                }
            )
        return calls

    @staticmethod
    def _method_call_arg_exprs(node: Any) -> list[Any]:
        args = next(
            (child for child in _ts_children(node) if getattr(child, "type", None) == "arguments"),
            None,
        )
        if args is None:
            return []
        return [
            child for child in _ts_children(args) if getattr(child, "type", None) == "expression"
        ]

    @staticmethod
    def _add_call(storage: DiagnosticStorage, lines: list[str], call_node: Any) -> None:
        _add_node_range(
            storage,
            code=MissingTemporaryFileDeletionRule.code,
            message=MissingTemporaryFileDeletionRule.message,
            severity=Severity.ERROR,
            lines=lines,
            start_node=call_node,
            end_node=call_node,
        )


class PairingBrokenTransactionRule(DiagnosticRuntimeRule):
    code = "BSL230"
    _begin_names = frozenset({"начатьтранзакцию", "begintransaction"})
    _pair_specs = (
        (
            frozenset(
                {
                    "начатьтранзакцию",
                    "begintransaction",
                    "зафиксироватьтранзакцию",
                    "committransaction",
                }
            ),
            {
                "начатьтранзакцию": "ЗафиксироватьТранзакцию",
                "begintransaction": "CommitTransaction",
                "зафиксироватьтранзакцию": "НачатьТранзакцию",
                "committransaction": "BeginTransaction",
            },
        ),
        (
            frozenset(
                {
                    "начатьтранзакцию",
                    "begintransaction",
                    "отменитьтранзакцию",
                    "rollbacktransaction",
                }
            ),
            {
                "начатьтранзакцию": "ОтменитьТранзакцию",
                "begintransaction": "RollbackTransaction",
                "отменитьтранзакцию": "НачатьТранзакцию",
                "rollbacktransaction": "BeginTransaction",
            },
        ),
    )

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        root = getattr(getattr(context.tree, "root_node", None), "text", None)
        if not isinstance(root, (bytes, bytearray)):
            return []
        global_calls, call_starts, proc_nodes, _try_nodes = (
            WrongUseOfRollbackTransactionMethodRule._runtime_context(context)
        )
        storage = DiagnosticStorage(context.path)
        for proc_node in proc_nodes:
            calls = _calls_in_node(proc_node, global_calls, call_starts)
            if calls:
                self._check_calls(storage, calls, context.lines)
        return storage.diagnostics

    def _check_calls(
        self, storage: DiagnosticStorage, calls: list[dict[str, Any]], lines: list[str]
    ) -> None:
        for allowed_names, pair_names in self._pair_specs:
            begin_stack: list[dict[str, Any]] = []
            for call in calls:
                name_cf = str(call["name"]).casefold()
                if name_cf not in allowed_names:
                    continue
                if name_cf in self._begin_names:
                    begin_stack.append(call)
                elif begin_stack:
                    begin_stack.pop()
                else:
                    self._add_call(storage, call, pair_names[name_cf], lines)
            for call in begin_stack:
                name_cf = str(call["name"]).casefold()
                self._add_call(storage, call, pair_names[name_cf], lines)

    def _add_call(
        self,
        storage: DiagnosticStorage,
        call: dict[str, Any],
        pair_name: str,
        lines: list[str],
    ) -> None:
        method_name = str(call["name"])
        line_idx = int(call["line"]) - 1
        end_character = int(call["end_character"])
        line_text = lines[line_idx] if 0 <= line_idx < len(lines) else ""
        leading = line_text[: int(call["character"])]
        if "\t" in leading and line_text[end_character : end_character + 2] == "()":
            end_character += 2
        storage.add_range(
            code=self.code,
            message=f'Отсутствует парный вызов "{pair_name}" для метода "{method_name}"',
            severity=Severity.ERROR,
            line=line_idx,
            character=int(call["character"]),
            end_line=line_idx,
            end_character=end_character,
        )


class BeginTransactionBeforeTryCatchRule(DiagnosticRuntimeRule):
    code = "BSL151"
    message = (
        "Метод 'НачатьТранзакцию' должен быть за пределами блока "
        "'Попытка-Исключение' непосредственно перед оператором 'Попытка'"
    )
    _statement_types = frozenset(
        {
            "assignment_statement",
            "break_statement",
            "call_statement",
            "continue_statement",
            "for_each_statement",
            "for_statement",
            "goto_statement",
            "if_statement",
            "return_statement",
            "rise_error_statement",
            "try_statement",
            "var_statement",
            "while_statement",
        }
    )
    _begin_names = frozenset({"начатьтранзакцию", "begintransaction"})

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        root = getattr(context.tree, "root_node", None)
        if root is None:
            return []

        storage = DiagnosticStorage(context.path)
        pending_begin: Any | None = None
        statements = sorted(
            (
                node
                for node in _ts_walk(root)
                if getattr(node, "type", None) in self._statement_types
                and not _diag.tree_has_errors(node)
            ),
            key=lambda node: (node.start_point[0], node.start_point[1], node.end_point[0]),
        )

        for statement in statements:
            if getattr(statement, "type", None) == "try_statement":
                pending_begin = None
                continue

            if pending_begin is not None:
                self._add_diagnostic(storage, context, pending_begin)
                pending_begin = None

            if self._is_global_begin_transaction(statement):
                pending_begin = statement

        if pending_begin is not None:
            self._add_diagnostic(storage, context, pending_begin)
        return storage.diagnostics

    @classmethod
    def _is_global_begin_transaction(cls, statement: Any) -> bool:
        if getattr(statement, "type", None) != "call_statement":
            return False
        children = _ts_children(statement)
        if not children or getattr(children[0], "type", None) != "method_call":
            return False
        method_call = children[0]
        for child in _ts_children(method_call):
            if getattr(child, "type", None) != "identifier":
                continue
            return _ts_node_text(child).casefold() in cls._begin_names
        return False

    def _add_diagnostic(
        self, storage: DiagnosticStorage, context: DiagnosticDocumentContext, statement: Any
    ) -> None:
        start_line = int(statement.start_point[0])
        end_line = int(statement.end_point[0])
        start_character = utf8_byte_offset_to_lsp_character(
            context.lines[start_line],
            int(statement.start_point[1]),
        )
        end_character = utf8_byte_offset_to_lsp_character(
            context.lines[end_line],
            int(statement.end_point[1]),
        )
        storage.add_range(
            code=self.code,
            message=self.message,
            severity=Severity.ERROR,
            line=start_line,
            character=start_character,
            end_line=end_line,
            end_character=end_character,
        )


class CodeBlockBeforeSubRule(DiagnosticRuntimeRule):
    code = "BSL155"
    message = "Необходимо разместить тело модуля после определения методов"
    _sub_types = {"procedure_definition", "function_definition"}
    _ignored_before_body_types = {"comment", "line_comment", "var_definition"}

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        if _path_is_split_module_fragment(context.path):
            return []

        root = getattr(context.tree, "root_node", None)
        if root is None:
            return []

        children = _ts_children(root)
        first_sub_index = self._first_sub_index(children)
        if first_sub_index is None:
            return []

        before_sub = children[:first_sub_index]
        executable_spans = [
            span for node in before_sub if (span := self._executable_body_span(node)) is not None
        ]
        if not executable_spans:
            return []

        start_node, _ = executable_spans[0]
        end_node = self._end_node(before_sub, start_node)
        storage = DiagnosticStorage(context.path)
        _add_node_range(
            storage,
            code=self.code,
            message=self.message,
            severity=Severity.ERROR,
            lines=context.lines,
            start_node=start_node,
            end_node=end_node,
        )
        return storage.diagnostics

    @classmethod
    def _first_sub_index(cls, children: list[Any]) -> int | None:
        for index, child in enumerate(children):
            if getattr(child, "type", None) in cls._sub_types:
                return index
        return None

    @classmethod
    def _is_executable_body_node(cls, node: Any) -> bool:
        return cls._executable_body_span(node) is not None

    @classmethod
    def _executable_body_span(cls, node: Any) -> tuple[Any, Any] | None:
        node_type = getattr(node, "type", None)
        if node_type in cls._ignored_before_body_types:
            return None
        if node_type in {"ERROR", "error"}:
            text = _ts_node_text(node).strip()
            first = text.split(None, 1)[0].rstrip(";,.")
            if first and "ё" in first.casefold() and first.replace("_", "").isalnum():
                return None
        if node_type != "preprocessor":
            return node, node

        skipped_preprocessor_parts = {
            "PREPROC_REGION_KEYWORD",
            "PREPROC_ENDREGION_KEYWORD",
            "PREPROC_IF_KEYWORD",
            "PREPROC_ELSIF_KEYWORD",
            "PREPROC_ELSE_KEYWORD",
            "PREPROC_ENDIF_KEYWORD",
            "THEN_KEYWORD",
            "annotation",
            "identifier",
            "expression",
            "string",
            "(",
            ")",
        }
        for child in _ts_children(node):
            if getattr(child, "type", None) in skipped_preprocessor_parts:
                continue
            if cls._executable_body_span(child) is not None:
                return child, node
        return None

    @classmethod
    def _end_node(cls, before_sub: list[Any], start_node: Any) -> Any:
        for node in before_sub:
            span = cls._executable_body_span(node)
            if span is not None and span[0] is start_node:
                start_node = node
                break
        try:
            start_index = before_sub.index(start_node)
        except ValueError:
            return start_node

        end_node = start_node
        for node in before_sub[start_index + 1 :]:
            node_type = getattr(node, "type", None)
            if node_type in cls._ignored_before_body_types:
                continue
            end_node = node
        return end_node


class LogicalOrInTheWhereSectionOfQueryRule(DiagnosticRuntimeRule):
    code = "BSL210"
    message = 'Не следует использовать логическое "ИЛИ" в секции "ГДЕ" запроса'
    _or_re = re.compile(r"\b(?:ИЛИ|OR)\b", re.IGNORECASE)
    _select_re = re.compile(r"\b(?:ВЫБРАТЬ|SELECT)\b", re.IGNORECASE)
    _where_re = re.compile(r"\b(?:ГДЕ|WHERE)\b", re.IGNORECASE)
    _continuation_re = re.compile(r"^\s*\|")
    _inline_comment_re = re.compile(r"\s*//.*$")
    _line_is_where_re = re.compile(r"^\s*(?:ГДЕ|WHERE)\b", re.IGNORECASE)
    _line_ends_where_re = re.compile(
        r"^\s*(?:СГРУППИРОВАТЬ|GROUP\s+BY|УПОРЯДОЧИТЬ|ORDER\s+BY|ИМЕЮЩИЕ|HAVING|"
        r"ИТОГИ|TOTALS|АВТОУПРЯДОЧИВАНИЕ|AUTOORDER|"
        r"ДЛЯ\s+ИЗМЕНЕНИЯ|FOR\s+UPDATE)\b",
        re.IGNORECASE,
    )
    _post_where_keyword_re = re.compile(
        r"\b(?:СГРУППИРОВАТЬ|GROUP\s+BY|УПОРЯДОЧИТЬ|ORDER\s+BY|ИМЕЮЩИЕ|HAVING|"
        r"ИТОГИ|TOTALS|АВТОУПРЯДОЧИВАНИЕ|AUTOORDER|ДЛЯ\s+ИЗМЕНЕНИЯ|FOR\s+UPDATE|"
        r"ОБЪЕДИНИТЬ|UNION)\b",
        re.IGNORECASE,
    )
    _clause_after_fields_re = re.compile(
        r"\b(?:ИЗ|FROM|ГДЕ|WHERE|СГРУППИРОВАТЬ|GROUP\s+BY|УПОРЯДОЧИТЬ|ORDER\s+BY|"
        r"ИМЕЮЩИЕ|HAVING|ИТОГИ|TOTALS|ОБЪЕДИНИТЬ|UNION)\b",
        re.IGNORECASE,
    )
    _union_re = re.compile(r"\bОБЪЕДИНИТЬ\b|\bUNION\b", re.IGNORECASE)

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        in_query = False
        group_depth = 0
        where_stack: list[int] = []

        for idx, line in enumerate(context.lines):
            stripped = line.rstrip()
            if not self._continuation_re.match(stripped):
                if in_query:
                    in_query = False
                    group_depth = 0
                    where_stack.clear()
                self._scan_line_literal_queries(storage, idx, line)
                select_match = self._select_re.search(stripped)
                if select_match:
                    tail = stripped[select_match.end() :]
                    if not self._clause_after_fields_re.search(tail):
                        in_query = True
                        group_depth = 0
                        where_stack.clear()
                continue

            if not in_query:
                if self._select_re.search(stripped):
                    in_query = True
                    group_depth = 0
                    where_stack.clear()
                else:
                    continue

            raw_content = stripped.lstrip()
            if raw_content.startswith("|"):
                raw_content = raw_content[1:]
            content = self._inline_comment_re.sub("", raw_content).rstrip().lstrip()

            line_rs = line.rstrip()
            pipe_pos = line_rs.find("|")
            if pipe_pos < 0:
                continue
            after_pipe = line_rs[pipe_pos + 1 :]
            leading_ws = len(after_pipe) - len(after_pipe.lstrip())
            content_base = pipe_pos + 1 + leading_ws

            quote_pos = self._closing_quote_pos(content)
            ended_query = quote_pos >= 0
            content_scan = content[:quote_pos].rstrip() if ended_query else content
            tail_has_semi = ";" in content_scan
            head = (
                content_scan[: content_scan.index(";")].rstrip() if tail_has_semi else content_scan
            )

            if tail_has_semi and not head:
                where_stack.clear()
                group_depth = 0
                if ended_query:
                    in_query = False
                continue
            if not head:
                if ended_query:
                    in_query = False
                    group_depth = 0
                    where_stack.clear()
                continue
            if self._union_re.search(head):
                where_stack.clear()
                continue
            if (
                where_stack
                and self._line_ends_where_re.match(head)
                and group_depth == where_stack[-1]
            ):
                where_stack.pop()
            if self._line_is_where_re.match(head):
                where_stack.append(group_depth)
            if where_stack:
                for match in self._or_re.finditer(head):
                    self._add_match(
                        storage, idx, content_base + match.start(), content_base + match.end()
                    )

            group_depth += head.count("(") - head.count(")")
            if group_depth < 0:
                group_depth = 0
            while where_stack and group_depth < where_stack[-1]:
                where_stack.pop()
            if tail_has_semi:
                where_stack.clear()
                group_depth = 0
            if ended_query:
                in_query = False
                group_depth = 0
                where_stack.clear()

        return storage.diagnostics

    def _scan_line_literal_queries(
        self, storage: DiagnosticStorage, line_idx: int, line: str
    ) -> None:
        if _line_comment(line):
            return
        for quote_pos, literal in self._double_quoted_segments(line):
            if not (self._select_re.search(literal) and self._where_re.search(literal)):
                continue
            offset_base = 0
            for part in literal.split(";"):
                for start, end in self._or_spans_in_query_literal(part):
                    self._add_match(
                        storage,
                        line_idx,
                        quote_pos + 1 + offset_base + start,
                        quote_pos + 1 + offset_base + end,
                    )
                offset_base += len(part) + 1

    def _add_match(
        self,
        storage: DiagnosticStorage,
        line_idx: int,
        start: int,
        end: int,
    ) -> None:
        storage.add_range(
            code=self.code,
            message=self.message,
            severity=Severity.WARNING,
            line=line_idx,
            character=start,
            end_line=line_idx,
            end_character=end,
        )

    def _where_clause_region_bounds(
        self, literal: str, where_match: re.Match[str]
    ) -> tuple[int, int]:
        pos = where_match.end()
        depth = 0
        while pos < len(literal):
            char = literal[pos]
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth < 0:
                    depth = 0
            if (
                depth == 0
                and pos > where_match.end()
                and self._post_where_keyword_re.match(literal, pos)
            ):
                return where_match.start(), pos
            pos += 1
        return where_match.start(), len(literal)

    def _or_spans_in_query_literal(self, literal: str) -> list[tuple[int, int]]:
        out: list[tuple[int, int]] = []
        pos = 0
        while True:
            match = self._where_re.search(literal, pos)
            if match is None:
                break
            _start, end = self._where_clause_region_bounds(literal, match)
            body = literal[match.end() : end]
            base = match.end()
            for or_match in self._or_re.finditer(body):
                out.append((base + or_match.start(), base + or_match.end()))
            pos = end
        return out

    @staticmethod
    def _closing_quote_pos(text: str) -> int:
        pos = 0
        while pos < len(text):
            if text[pos] != '"':
                pos += 1
                continue
            if pos + 1 < len(text) and text[pos + 1] == '"':
                pos += 2
                continue
            return pos
        return -1

    @staticmethod
    def _double_quoted_segments(line: str):
        pos = 0
        while pos < len(line):
            if line[pos] != '"':
                pos += 1
                continue
            quote_pos = pos
            pos += 1
            buf: list[str] = []
            while pos < len(line):
                if line[pos] == '"':
                    if pos + 1 < len(line) and line[pos + 1] == '"':
                        buf.append('"')
                        pos += 2
                        continue
                    break
                buf.append(line[pos])
                pos += 1
            yield quote_pos, "".join(buf)
            pos += 1


class CommitTransactionOutsideTryCatchRule(DiagnosticRuntimeRule):
    code = "BSL157"
    message = (
        "Метод 'ЗафиксироватьТранзакцию' должен идти последним в блоке "
        "'Попытка' перед оператором 'Исключение'"
    )
    _commit_re = re.compile(
        r"^\s*(?:ЗафиксироватьТранзакцию|CommitTransaction)\s*\(", re.IGNORECASE
    )
    _try_re = re.compile(r"^\s*(?:Попытка|Try)\b", re.IGNORECASE)
    _except_re = re.compile(r"^\s*(?:Исключение|Except)\b", re.IGNORECASE)
    _end_try_re = re.compile(r"^\s*(?:КонецПопытки|EndTry)\b", re.IGNORECASE)

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        clean_lines = (
            context.snapshot.code_lines_without_comments
            if context.snapshot is not None
            else context.lines
        )
        storage = DiagnosticStorage(context.path)
        pending: tuple[int, int, int] | None = None

        for idx, line in enumerate(clean_lines):
            if not line.strip():
                continue

            if self._try_re.match(line):
                if pending is not None:
                    self._add_pending(storage, pending)
                pending = None
                continue

            if self._except_re.match(line):
                pending = None
                continue

            if self._end_try_re.match(line):
                if pending is not None:
                    self._add_pending(storage, pending)
                pending = None
                continue

            match = self._commit_re.search(line)
            if match:
                pending = (
                    idx,
                    len(line) - len(line.lstrip()),
                    len(_code_before_comment(line).rstrip()),
                )
                continue

            if pending is not None:
                self._add_pending(storage, pending)
                pending = None

        if pending is not None:
            self._add_pending(storage, pending)
        return storage.diagnostics

    def _add_pending(self, storage: DiagnosticStorage, pending: tuple[int, int, int]) -> None:
        line, character, end_character = pending
        storage.add_range(
            code=self.code,
            message=self.message,
            severity=Severity.ERROR,
            line=line,
            character=character,
            end_line=line,
            end_character=end_character,
        )


class IncorrectLineBreakRule(DiagnosticRuntimeRule):
    code = "BSL200"

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        assert context.snapshot is not None
        return [
            Diagnostic(
                file=context.path,
                line=fact.line_idx + 1,
                character=fact.character,
                end_line=fact.line_idx + 1,
                end_character=fact.end_character,
                severity=Severity.INFORMATION,
                code=self.code,
                message=fact.message,
            )
            for fact in context.snapshot.incorrect_line_break_facts
        ]


class AssignAliasFieldsInQueryRule(DiagnosticRuntimeRule):
    code = "BSL149"
    message = "Полям запроса следует назначать псевдонимы"

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        from onec_hbk_bsl.analysis.diagnostic.rules.query_runtime_rules import (
            run_bsl149_assign_alias_fields_in_query,
        )

        query_blocks = context.query_text_blocks if context.snapshot is not None else None
        return run_bsl149_assign_alias_fields_in_query(context.path, context.lines, query_blocks)


class OneStatementPerLineRule(DiagnosticRuntimeRule):
    code = "BSL227"
    message = "Перенесите выражение на новую строку"
    _then_re = re.compile(r"\b(?:тогда|then)\b", re.IGNORECASE)
    _end_if_re = re.compile(r"^(?:конецесли|endif)\s*;?\s*$", re.IGNORECASE)

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        string_states = (
            context.snapshot.line_string_states
            if context.snapshot is not None
            else build_line_string_states(context.lines)
        )
        for idx, line in enumerate(context.lines):
            stripped = line.lstrip()
            if not stripped or stripped.startswith("//") or stripped.startswith("#"):
                continue

            clean = _code_mask_without_strings_and_comments(line, string_states[idx])
            spans = self._statement_spans(clean)
            if len(spans) <= 1:
                continue
            for start, end in spans[1:]:
                storage.add_range(
                    code=self.code,
                    message=self.message,
                    severity=Severity.INFORMATION,
                    line=idx,
                    character=start,
                    end_line=idx,
                    end_character=end,
                )
        return storage.diagnostics

    @staticmethod
    def _statement_spans(clean: str) -> list[tuple[int, int]]:
        spans: list[tuple[int, int]] = []
        stmt_start = 0
        depth = 0
        for idx, ch in enumerate(clean):
            if ch == "(":
                depth += 1
                continue
            if ch == ")" and depth > 0:
                depth -= 1
                continue
            if ch != ";" or depth != 0:
                continue
            segment = clean[stmt_start : idx + 1]
            text = segment.strip()
            if text and text != ";":
                start = stmt_start + len(segment) - len(segment.lstrip())
                end = idx + 1
                spans.append((start, end))
            stmt_start = idx + 1
        expanded: list[tuple[int, int]] = []
        for start, end in spans:
            segment = clean[start:end]
            expanded.append((start, end))
            then_match = OneStatementPerLineRule._then_re.search(segment)
            if then_match is None:
                continue
            tail = segment[then_match.end() :]
            if ";" not in tail:
                continue
            sub = tail[: tail.rfind(";")].strip()
            if not sub:
                continue
            sub_start = (
                start
                + then_match.end()
                + len(tail[: tail.rfind(";")])
                - len(tail[: tail.rfind(";")].lstrip())
            )
            expanded.append((sub_start, end))
        spans = expanded
        spans = [
            (start, end)
            for start, end in spans
            if not OneStatementPerLineRule._end_if_re.match(clean[start:end].strip())
        ]
        return spans


class UnaryPlusInConcatenationRule(DiagnosticRuntimeRule):
    code = "BSL257"
    message = "Унарный плюс в конкатенации строк потенциально приводит к ошибке времени выполнения"

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        source_bytes = getattr(getattr(context.tree, "root_node", None), "text", None)
        if not isinstance(source_bytes, (bytes, bytearray)):
            return []

        storage = DiagnosticStorage(context.path)
        for unary_node in context.ts_nodes_for_types(context.tree, {"unary_expression"})[
            "unary_expression"
        ]:
            operator = next(
                (
                    child
                    for child in _ts_children(unary_node)
                    if getattr(child, "type", None) == "operator" and _ts_node_text(child) == "+"
                ),
                None,
            )
            if operator is None or self._has_numeric_operand(unary_node):
                continue
            if not self._previous_non_space_is_plus(source_bytes, int(operator.start_byte)):
                continue
            _add_node_range(
                storage,
                code=self.code,
                message=self.message,
                severity=Severity.ERROR,
                lines=context.lines,
                start_node=operator,
                end_node=operator,
            )
        return storage.diagnostics

    @staticmethod
    def _previous_non_space_is_plus(source_bytes: bytes | bytearray, start_byte: int) -> bool:
        pos = start_byte - 1
        while pos >= 0 and source_bytes[pos] in b" \t\r\n":
            pos -= 1
        return pos >= 0 and source_bytes[pos] == ord("+")

    @staticmethod
    def _has_numeric_operand(unary_node: Any) -> bool:
        operand = next(
            (
                child
                for child in _ts_children(unary_node)
                if getattr(child, "type", None) == "expression"
            ),
            None,
        )
        return operand is not None and any(
            getattr(child, "type", None) == "number" for child in _ts_walk(operand)
        )


class UnionAllRule(DiagnosticRuntimeRule):
    code = "BSL258"
    message = "Замените конструкцию ОБЪЕДИНИТЬ на ОБЪЕДИНИТЬ ВСЕ"

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        in_query = False
        for idx, line in enumerate(context.lines):
            stripped = line.strip()
            if stripped.startswith("//"):
                continue
            if '|"' in line or stripped.startswith("|"):
                in_query = True
            if stripped.endswith('";') or (stripped.endswith('"') and "ВЫБРАТЬ" not in stripped):
                in_query = False
            if not in_query and "|" not in line and '"' not in line:
                continue
            match = _BSL258_UNION_RE.search(line)
            if match is None:
                continue
            storage.add_range(
                code=self.code,
                message=self.message,
                severity=Severity.INFORMATION,
                line=idx,
                character=match.start(),
                end_line=idx,
                end_character=match.end(),
            )
        return storage.diagnostics


class UsageWriteLogEventRule(DiagnosticRuntimeRule):
    code = "BSL262"
    _target_names = frozenset({"записьжурналарегистрации", "writelogevent"})
    _level_root_names = frozenset({"уровеньжурналарегистрации", "eventloglevel"})
    _error_level_names = frozenset({"ошибка", "error"})
    _detail_error_names = frozenset({"подробноепредставлениеошибки", "detailerrordescription"})
    _brief_error_names = frozenset({"краткоепредставлениеошибки", "brieferrordescription"})
    _simple_error_names = frozenset({"описаниеошибки", "errordescription"})
    _error_info_names = frozenset({"информацияобошибке", "errorinfo"})
    _raise_names = frozenset({"ВЫЗВАТЬИСКЛЮЧЕНИЕ_KEYWORD", "RAISE_KEYWORD"})
    _message_wrong_number = "Неверное число параметров метода"
    _message_no_second = 'Не указан 2й параметр с типом "УровеньЖурналаРегистрации"'
    _message_no_comment = 'Не указан 5й параметр "Комментарий"'
    _message_no_error_level = 'Нужно указывать уровень "Ошибка" при записи в журнал регистрации внутри блока Исключение-КонецПопытки'
    _message_no_detail = (
        'В тексте комментария нет вызова "ПодробноеПредставлениеОшибки(ИнформацияОбОшибке())"'
    )

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        root = getattr(getattr(context.tree, "root_node", None), "text", None)
        if not isinstance(root, (bytes, bytearray)):
            return []
        content_cf = context.content.casefold()
        if not any(name in content_cf for name in self._target_names):
            return []
        global_calls, call_starts, _proc_nodes, try_nodes = (
            WrongUseOfRollbackTransactionMethodRule._runtime_context(context)
        )
        except_blocks = self._except_blocks(try_nodes, global_calls, call_starts)
        storage = DiagnosticStorage(context.path)
        for call in global_calls:
            if str(call["name"]).casefold() not in self._target_names:
                continue
            call_node = call["node"]
            args = self._call_params(call_node)
            if len(args) < 5:
                self._add_call(storage, context.lines, call_node, self._message_wrong_number)
                continue
            if args[1] is None:
                self._add_call(storage, context.lines, call_node, self._message_no_second)
                continue
            if args[4] is None:
                self._add_call(storage, context.lines, call_node, self._message_no_comment)
                continue
            except_roots = except_blocks.get(id(call_node))
            if except_roots is None:
                continue
            if not self._has_error_log_level(args[1]):
                self._add_call(storage, context.lines, call_node, self._message_no_error_level)
                continue
            if not self._is_comment_correct(except_roots, args[4]):
                self._add_call(storage, context.lines, call_node, self._message_no_detail)
        return storage.diagnostics

    @staticmethod
    def _call_params(call_node: Any) -> list[Any | None]:
        args_node = next(
            (
                child
                for child in _ts_children(call_node)
                if getattr(child, "type", None) == "arguments"
            ),
            None,
        )
        if args_node is None:
            return []
        params: list[Any | None] = []
        current: Any | None = None
        for child in _ts_children(args_node):
            child_type = getattr(child, "type", None)
            if child_type in {"(", ")", "line_comment", "comment"}:
                continue
            if child_type == ",":
                params.append(current)
                current = None
                continue
            if child_type == "omitted_argument":
                params.append(current)
                current = None
                continue
            if child_type == "expression":
                current = child
        params.append(current)
        return params

    @staticmethod
    def _except_blocks(
        try_nodes: list[Any],
        global_calls: list[dict[str, Any]],
        call_starts: list[int],
    ) -> dict[int, list[Any]]:
        blocks: dict[int, list[Any]] = {}
        for try_node in try_nodes:
            children = _ts_children(try_node)
            except_idx = next(
                (
                    idx
                    for idx, child in enumerate(children)
                    if getattr(child, "type", None) == "EXCEPT_KEYWORD"
                ),
                None,
            )
            if except_idx is None:
                continue
            end_idx = next(
                (
                    idx
                    for idx, child in enumerate(children)
                    if getattr(child, "type", None) == "ENDTRY_KEYWORD"
                ),
                len(children),
            )
            roots = children[except_idx + 1 : end_idx]
            for root in roots:
                for call in _calls_in_node(root, global_calls, call_starts):
                    blocks[id(call["node"])] = roots
        return blocks

    @classmethod
    def _has_error_log_level(cls, expr: Any) -> bool:
        text = _ts_node_text(expr).casefold()
        if not any(root_name in text for root_name in cls._level_root_names):
            return True
        if "." not in text:
            return True
        return any(error_name in text for error_name in cls._error_level_names)

    @classmethod
    def _is_comment_correct(cls, block_roots: list[Any], expr: Any | None) -> bool:
        if expr is None:
            return True
        if cls._block_has_raise(block_roots):
            return True
        return cls._is_valid_comment_expression(block_roots, expr, check_assignment=True)

    @classmethod
    def _is_valid_comment_expression(
        cls,
        block_roots: list[Any],
        expr: Any,
        *,
        check_assignment: bool,
    ) -> bool:
        call_names = [cls._method_name(call) for call in cls._method_calls(expr)]
        call_names_cf = [name.casefold() for name in call_names if name]
        if any(name in cls._detail_error_names for name in call_names_cf) and any(
            name in cls._error_info_names for name in call_names_cf
        ):
            return True
        if check_assignment and any(name in cls._detail_error_names for name in call_names_cf):
            for ident in cls._identifiers(expr):
                assignment_expr = cls._first_assignment_expr(block_roots, ident)
                if assignment_expr is None:
                    continue
                assigned_call_names = [
                    cls._method_name(call).casefold() for call in cls._method_calls(assignment_expr)
                ]
                if any(name in cls._error_info_names for name in assigned_call_names):
                    return True
        if any(
            name in cls._simple_error_names or name in cls._brief_error_names
            for name in call_names_cf
        ):
            return False
        if cls._expression_is_const(expr):
            return False
        if check_assignment:
            identifier = cls._single_identifier(expr)
            if identifier is not None:
                assignment_expr = cls._first_assignment_expr(block_roots, identifier)
                if assignment_expr is None:
                    return True
                return cls._is_valid_comment_expression(
                    block_roots,
                    assignment_expr,
                    check_assignment=False,
                )
        return False

    @staticmethod
    def _method_calls(node: Any) -> list[Any]:
        return [child for child in _ts_walk(node) if getattr(child, "type", None) == "method_call"]

    @staticmethod
    def _method_name(node: Any) -> str:
        ident = next(
            (child for child in _ts_children(node) if getattr(child, "type", None) == "identifier"),
            None,
        )
        return _ts_node_text(ident) if ident is not None else ""

    @staticmethod
    def _expression_is_const(expr: Any) -> bool:
        return any(getattr(child, "type", None) == "const_value" for child in _ts_walk(expr))

    @staticmethod
    def _single_identifier(expr: Any) -> str | None:
        children = _ts_children(expr)
        if len(children) != 1:
            return None
        member = children[0]
        if getattr(member, "type", None) == "identifier":
            text = _ts_node_text(member).strip()
            return text if text else None
        if getattr(member, "type", None) != "member":
            return None
        text = _ts_node_text(member).strip()
        return (
            text if text and re.fullmatch(r"[А-ЯЁа-яёA-Za-z_][А-ЯЁа-яёA-Za-z_0-9]*", text) else None
        )

    @staticmethod
    def _identifiers(expr: Any) -> list[str]:
        result: list[str] = []
        for node in _ts_walk(expr):
            if getattr(node, "type", None) not in {"identifier", "member"}:
                continue
            text = _ts_node_text(node).strip()
            if re.fullmatch(r"[А-ЯЁа-яёA-Za-z_][А-ЯЁа-яёA-Za-z_0-9]*", text):
                result.append(text)
        return result

    @staticmethod
    def _first_assignment_expr(block_roots: list[Any], var_name: str) -> Any | None:
        assignment = next(
            (root for root in block_roots if getattr(root, "type", None) == "assignment_statement"),
            None,
        )
        if assignment is None:
            return None
        children = _ts_children(assignment)
        eq_idx = next(
            (idx for idx, child in enumerate(children) if getattr(child, "type", None) == "="),
            None,
        )
        if eq_idx is None:
            return None
        lvalue = "".join(_ts_node_text(child) for child in children[:eq_idx]).strip()
        if lvalue.casefold() != var_name.casefold():
            return None
        return next(
            (
                child
                for child in children[eq_idx + 1 :]
                if getattr(child, "type", None) == "expression"
            ),
            None,
        )

    @classmethod
    def _block_has_raise(cls, block_roots: list[Any]) -> bool:
        return any(
            getattr(node, "type", None) in cls._raise_names
            for root in block_roots
            for node in _ts_walk(root)
        )

    @staticmethod
    def _add_call(
        storage: DiagnosticStorage, lines: list[str], call_node: Any, message: str
    ) -> None:
        _add_node_range(
            storage,
            code=UsageWriteLogEventRule.code,
            message=message,
            severity=Severity.INFORMATION,
            lines=lines,
            start_node=call_node,
            end_node=call_node,
        )


class WrongUseOfRollbackTransactionMethodRule(DiagnosticRuntimeRule):
    code = "BSL277"
    message = "Метод ОтменитьТранзакцию() должен быть в попытке и первым методом блока исключения"

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        root = getattr(getattr(context.tree, "root_node", None), "text", None)
        if not isinstance(root, (bytes, bytearray)):
            return []
        content_cf = context.content.casefold()
        if not any(name in content_cf for name in _BSL277_ROLLBACK_NAMES):
            return []
        global_calls, call_starts, _proc_nodes, try_nodes = self._runtime_context(context)
        storage = DiagnosticStorage(context.path)
        rollback_in_except_ids: set[int] = set()

        for try_node in try_nodes:
            except_calls = self._except_calls(try_node, global_calls, call_starts)
            if not except_calls:
                continue
            rollback_is_first = str(except_calls[0]["name"]).casefold() in _BSL277_ROLLBACK_NAMES
            for call in except_calls:
                if str(call["name"]).casefold() not in _BSL277_ROLLBACK_NAMES:
                    continue
                rollback_in_except_ids.add(id(call["node"]))
                if not rollback_is_first:
                    self._add_call(storage, call)

        for call in global_calls:
            if str(call["name"]).casefold() not in _BSL277_ROLLBACK_NAMES:
                continue
            if id(call["node"]) in rollback_in_except_ids:
                continue
            self._add_call(storage, call)
        return storage.diagnostics

    @staticmethod
    def _runtime_context(
        context: DiagnosticDocumentContext,
    ) -> tuple[list[Any], list[int], list[Any], list[Any]]:
        cached = context.runtime_call_context
        if cached is not None:
            return cached
        if context.ts_nodes_for_types and context.global_method_calls_from_nodes:
            nodes = context.ts_nodes_for_types(
                context.tree,
                {"method_call", "procedure_definition", "function_definition", "try_statement"},
            )
            global_calls = context.global_method_calls_from_nodes(
                nodes["method_call"], context.lines
            )
            call_starts = [getattr(call["node"], "start_byte", -1) for call in global_calls]
            proc_nodes = nodes["procedure_definition"] + nodes["function_definition"]
            return global_calls, call_starts, proc_nodes, nodes["try_statement"]

        from onec_hbk_bsl.analysis import diagnostics as _diag

        root = context.tree.root_node
        global_calls = _diag._ts_global_method_calls(root, context.lines)
        call_starts = [getattr(call["node"], "start_byte", -1) for call in global_calls]
        proc_nodes = [
            node
            for node in _diag._ts_walk(root)
            if getattr(node, "type", None) in {"procedure_definition", "function_definition"}
        ]
        try_nodes = [
            node for node in _diag._ts_walk(root) if getattr(node, "type", None) == "try_statement"
        ]
        return global_calls, call_starts, proc_nodes, try_nodes

    @staticmethod
    def _except_calls(
        try_node: Any,
        global_calls: list[dict[str, Any]],
        call_starts: list[int],
    ) -> list[dict[str, Any]]:
        children = list(getattr(try_node, "children", []) or [])
        except_idx = next(
            (
                idx
                for idx, child in enumerate(children)
                if getattr(child, "type", None) == "EXCEPT_KEYWORD"
            ),
            None,
        )
        if except_idx is None:
            return []
        endtry_idx = next(
            (
                idx
                for idx, child in enumerate(children)
                if getattr(child, "type", None) == "ENDTRY_KEYWORD"
            ),
            len(children),
        )
        calls: list[dict[str, Any]] = []
        for child in children[except_idx + 1 : endtry_idx]:
            calls.extend(_calls_in_node(child, global_calls, call_starts))
        return calls

    def _add_call(self, storage: DiagnosticStorage, call: dict[str, Any]) -> None:
        storage.add_range(
            code=self.code,
            message=self.message,
            severity=Severity.ERROR,
            line=int(call["line"]) - 1,
            character=int(call["character"]),
            end_line=int(call["line"]) - 1,
            end_character=int(call["end_character"]),
        )


class WrongUseFunctionProceedWithCallRule(DiagnosticRuntimeRule):
    code = "BSL276"
    message = (
        "Использовать функцию ПродолжитьВызов() можно только в расширениях "
        "и только в методах с аннотацией &Вместо."
    )

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        root = getattr(getattr(context.tree, "root_node", None), "text", None)
        if not isinstance(root, (bytes, bytearray)):
            return []
        content_cf = context.content.casefold()
        if not any(name in content_cf for name in _BSL276_PROCEED_NAMES):
            return []
        global_calls, _call_starts, _proc_nodes, _try_nodes = (
            WrongUseOfRollbackTransactionMethodRule._runtime_context(context)
        )
        storage = DiagnosticStorage(context.path)
        procs = list(getattr(context.snapshot, "procedures", []) or [])
        if not procs:
            procs = ExecuteExternalCodeRule._fallback_procs(context.lines)

        for call in global_calls:
            if str(call["name"]).casefold() not in _BSL276_PROCEED_NAMES:
                continue
            line = int(call["line"]) - 1
            proc = self._proc_containing_line(procs, line)
            if proc is None:
                continue
            if self._has_around_annotation(context.lines, int(proc.start_idx)):
                continue
            storage.add_range(
                code=self.code,
                message=self.message,
                severity=Severity.ERROR,
                line=line,
                character=int(call["character"]),
                end_line=line,
                end_character=int(call["end_character"]),
            )
        return storage.diagnostics

    @staticmethod
    def _proc_containing_line(procs: list[Any], line: int) -> Any | None:
        for proc in procs:
            if int(proc.start_idx) <= line <= int(proc.end_idx):
                return proc
        return None

    @staticmethod
    def _has_around_annotation(lines: list[str], proc_start_idx: int) -> bool:
        annotation_lines = lines[max(0, proc_start_idx - 3) : proc_start_idx + 1]
        return any(_BSL276_AROUND_ANNOTATION_RE.match(line) for line in annotation_lines)


class TryNumberRule(DiagnosticRuntimeRule):
    code = "BSL255"
    message = "Не следует использовать исключения для приведения значения к типу"
    _NUMBER_CALL_RE = re.compile(r"\b(?:Число|Number)\s*\(", re.IGNORECASE)

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        if self._NUMBER_CALL_RE.search(context.content) is None:
            return []
        root = getattr(getattr(context.tree, "root_node", None), "text", None)
        if not isinstance(root, (bytes, bytearray)):
            return self._regex_fallback(context)
        try_nodes = self._try_nodes(context)
        storage = DiagnosticStorage(context.path)
        seen: set[int] = set()

        for try_node in try_nodes:
            for call_node in self._try_code_block_method_calls(try_node):
                if id(call_node) in seen:
                    continue
                if self._method_name(call_node).casefold() not in _BSL255_NUMBER_NAMES:
                    continue
                seen.add(id(call_node))
                _add_node_range(
                    storage,
                    code=self.code,
                    message=self.message,
                    severity=Severity.WARNING,
                    lines=context.lines,
                    start_node=call_node,
                    end_node=call_node,
                )
        existing = {(d.line, d.character) for d in storage.diagnostics}
        for diag in self._regex_fallback(context):
            if (diag.line, diag.character) not in existing:
                storage.diagnostics.append(diag)
        return storage.diagnostics

    @staticmethod
    def _try_nodes(context: DiagnosticDocumentContext) -> list[Any]:
        if context.ts_nodes_for_types:
            return context.ts_nodes_for_types(context.tree, {"try_statement"})["try_statement"]
        root = getattr(context.tree, "root_node", None)
        return [node for node in _ts_walk(root) if getattr(node, "type", None) == "try_statement"]

    @staticmethod
    def _try_code_block_method_calls(try_node: Any) -> list[Any]:
        calls: list[Any] = []
        for child in _ts_children(try_node):
            child_type = getattr(child, "type", None)
            if child_type == "EXCEPT_KEYWORD":
                break
            if child_type in {"TRY_KEYWORD", "ENDTRY_KEYWORD"}:
                continue
            calls.extend(
                node for node in _ts_walk(child) if getattr(node, "type", None) == "method_call"
            )
        return calls

    @staticmethod
    def _method_name(node: Any) -> str:
        ident = next(
            (child for child in _ts_children(node) if getattr(child, "type", None) == "identifier"),
            None,
        )
        return _ts_node_text(ident) if ident is not None else ""

    @classmethod
    def _regex_fallback(cls, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        try_depth = 0
        in_try_body_stack: list[bool] = []
        for line_idx, line in enumerate(context.lines):
            code = line.split("//", 1)[0].rstrip()
            if re.match(r"^\s*(?:Попытка|Try)\b", code, re.IGNORECASE):
                try_depth += 1
                in_try_body_stack.append(True)
                continue
            if try_depth and re.match(r"^\s*(?:Исключение|Except)\b", code, re.IGNORECASE):
                in_try_body_stack[-1] = False
                continue
            if re.match(r"^\s*(?:КонецПопытки|EndTry)\b", code, re.IGNORECASE):
                if try_depth:
                    try_depth -= 1
                    in_try_body_stack.pop()
                continue
            if not try_depth or not any(in_try_body_stack):
                continue
            for match in cls._NUMBER_CALL_RE.finditer(code):
                open_paren = match.end() - 1
                depth = 0
                end = len(code.rstrip().rstrip(";"))
                for pos in range(open_paren, len(code)):
                    char = code[pos]
                    if char == "(":
                        depth += 1
                    elif char == ")":
                        depth -= 1
                        if depth == 0:
                            end = pos + 1
                            break
                storage.add_range(
                    code=cls.code,
                    message=cls.message,
                    severity=Severity.WARNING,
                    line=line_idx,
                    character=match.start(),
                    end_line=line_idx,
                    end_character=end,
                )
        return storage.diagnostics

    @staticmethod
    def _try_code_block_calls(
        try_node: Any,
        global_calls: list[dict[str, Any]],
        call_starts: list[int],
    ) -> list[dict[str, Any]]:
        children = list(getattr(try_node, "children", []) or [])
        try_idx = next(
            (
                idx
                for idx, child in enumerate(children)
                if getattr(child, "type", None) == "TRY_KEYWORD"
            ),
            None,
        )
        except_idx = next(
            (
                idx
                for idx, child in enumerate(children)
                if getattr(child, "type", None) == "EXCEPT_KEYWORD"
            ),
            len(children),
        )
        if try_idx is None:
            return []
        calls: list[dict[str, Any]] = []
        for child in children[try_idx + 1 : except_idx]:
            calls.extend(_calls_in_node(child, global_calls, call_starts))
        return calls


class UseLessForEachRule(DiagnosticRuntimeRule):
    code = "BSL263"
    message = "Итератор не используется в теле цикла"

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        root = getattr(getattr(context.tree, "root_node", None), "text", None)
        if not isinstance(root, (bytes, bytearray)):
            return []
        module_vars = self._module_variable_names(context.tree.root_node)
        storage = DiagnosticStorage(context.path)

        for node in context.ts_nodes_for_types(context.tree, {"for_each_statement"})[
            "for_each_statement"
        ]:
            iterator = self._iterator_node(node)
            if iterator is None:
                continue
            iterator_name = _ts_node_text(iterator)
            if iterator_name.casefold() in module_vars:
                continue
            body_nodes = self._body_nodes(node)
            if not body_nodes:
                continue
            if self._has_iterator_usage(body_nodes, iterator_name):
                continue
            _add_node_range(
                storage,
                code=self.code,
                message=self.message,
                severity=Severity.ERROR,
                lines=context.lines,
                start_node=iterator,
                end_node=iterator,
            )
        return storage.diagnostics

    @staticmethod
    def _module_variable_names(root: Any) -> set[str]:
        names: set[str] = set()
        for node in _ts_walk(root):
            if getattr(node, "type", None) != "var_definition":
                continue
            if getattr(getattr(node, "parent", None), "type", None) != "source_file":
                continue
            for child in _ts_walk(node):
                if getattr(child, "type", None) == "identifier":
                    names.add(_ts_node_text(child).casefold())
        return names

    @staticmethod
    def _iterator_node(node: Any) -> Any | None:
        seen_each = False
        for child in _ts_children(node):
            child_type = getattr(child, "type", None)
            if child_type == "EACH_KEYWORD":
                seen_each = True
                continue
            if seen_each and child_type == "identifier":
                return child
        return None

    @staticmethod
    def _body_nodes(node: Any) -> list[Any]:
        children = _ts_children(node)
        do_idx = next(
            (
                idx
                for idx, child in enumerate(children)
                if getattr(child, "type", None) == "DO_KEYWORD"
            ),
            None,
        )
        end_idx = next(
            (
                idx
                for idx, child in enumerate(children)
                if getattr(child, "type", None) == "ENDDO_KEYWORD"
            ),
            len(children),
        )
        if do_idx is None:
            return []
        return children[do_idx + 1 : end_idx]

    @staticmethod
    def _has_iterator_usage(body_nodes: list[Any], iterator_name: str) -> bool:
        iterator_cf = iterator_name.casefold()
        for body_node in body_nodes:
            for node in _ts_walk(body_node):
                if getattr(node, "type", None) != "identifier":
                    continue
                if _ts_node_text(node).casefold() != iterator_cf:
                    continue
                parent = getattr(node, "parent", None)
                if getattr(parent, "type", None) == "method_call":
                    continue
                return True
        return False


class IfElseIfEndsWithElseRule(DiagnosticRuntimeRule):
    code = "BSL199"
    message = (
        'Синтаксическая конструкция вида "Если...Тогда...ИначеЕсли..." '
        'должна содержать ветвь "Иначе".'
    )

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        root = getattr(getattr(context.tree, "root_node", None), "text", None)
        if not isinstance(root, (bytes, bytearray)):
            return []
        storage = DiagnosticStorage(context.path)
        for node in context.ts_nodes_for_types(context.tree, {"if_statement"})["if_statement"]:
            children = _ts_children(node)
            has_elseif = any(getattr(child, "type", None) == "elseif_clause" for child in children)
            has_else = any(getattr(child, "type", None) == "else_clause" for child in children)
            if not has_elseif or has_else:
                continue
            endif_node = next(
                (
                    child
                    for child in reversed(children)
                    if getattr(child, "type", None) == "ENDIF_KEYWORD"
                ),
                None,
            )
            if endif_node is None:
                continue
            _add_node_range(
                storage,
                code=self.code,
                message=self.message,
                severity=Severity.WARNING,
                lines=context.lines,
                start_node=endif_node,
                end_node=endif_node,
            )
        return storage.diagnostics


class IfElseDuplicatedConditionRule(DiagnosticRuntimeRule):
    code = "BSL198"
    message = (
        'Синтаксическая конструкция "Если...Тогда...ИначеЕсли..." содержит повторяющиеся условия'
    )

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        root = getattr(getattr(context.tree, "root_node", None), "text", None)
        if not isinstance(root, (bytes, bytearray)):
            return []
        storage = DiagnosticStorage(context.path)
        key_cache: dict[int, tuple[Any, ...]] = {}
        for node in context.ts_nodes_for_types(context.tree, {"if_statement"})["if_statement"]:
            expressions = self._branch_expressions_with_ranges(node)
            reported: set[tuple[Any, ...]] = set()
            for index, (expression, start_node, end_node) in enumerate(expressions[:-1]):
                key = _structural_node_key(expression, key_cache)
                if key in reported:
                    continue
                if any(
                    _structural_node_key(candidate, key_cache) == key
                    for candidate, _, _ in expressions[index + 1 :]
                ):
                    _add_node_range(
                        storage,
                        code=self.code,
                        message=self.message,
                        severity=Severity.WARNING,
                        lines=context.lines,
                        start_node=start_node,
                        end_node=end_node,
                    )
                    reported.add(key)
        return storage.diagnostics

    @staticmethod
    def _branch_expressions_with_ranges(if_statement: Any) -> list[tuple[Any, Any, Any]]:
        expressions: list[tuple[Any, Any, Any]] = []
        for child in _ts_children(if_statement):
            child_type = getattr(child, "type", None)
            if child_type == "expression":
                expressions.append(
                    (child, *IfElseDuplicatedConditionRule._diagnostic_nodes(if_statement, child))
                )
            elif child_type == "elseif_clause":
                expression = next(
                    (
                        clause_child
                        for clause_child in _ts_children(child)
                        if getattr(clause_child, "type", None) == "expression"
                    ),
                    None,
                )
                if expression is not None:
                    expressions.append(
                        (
                            expression,
                            *IfElseDuplicatedConditionRule._diagnostic_nodes(child, expression),
                        )
                    )
        return expressions

    @staticmethod
    def _diagnostic_nodes(parent: Any, expression: Any) -> tuple[Any, Any]:
        children = _ts_children(parent)
        try:
            index = children.index(expression)
        except ValueError:
            return expression, expression
        start_node = expression
        end_node = expression
        if index > 0:
            previous = children[index - 1]
            if getattr(previous, "type", None) == "ERROR" and _ts_node_text(previous) == "(":
                start_node = previous
        if index + 1 < len(children):
            following = children[index + 1]
            if getattr(following, "type", None) == "ERROR" and _ts_node_text(following) == ")":
                end_node = following
        return start_node, end_node


class IfElseDuplicatedCodeBlockRule(DiagnosticRuntimeRule):
    code = "BSL197"
    message = (
        'Синтаксическая конструкция "Если...Тогда...ИначеЕсли..." содержит повторяющиеся блоки кода'
    )

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        root = getattr(getattr(context.tree, "root_node", None), "text", None)
        if not isinstance(root, (bytes, bytearray)):
            return []
        storage = DiagnosticStorage(context.path)
        key_cache: dict[int, tuple[Any, ...]] = {}
        for node in context.ts_nodes_for_types(context.tree, {"if_statement"})["if_statement"]:
            blocks = self._branch_blocks(node)
            reported: set[tuple[Any, ...]] = set()
            for index, block in enumerate(blocks[:-1]):
                key = self._block_key(block, key_cache)
                if not key or key in reported:
                    continue
                if any(
                    self._block_key(candidate, key_cache) == key
                    for candidate in blocks[index + 1 :]
                ):
                    _add_node_range(
                        storage,
                        code=self.code,
                        message=self.message,
                        severity=Severity.INFORMATION,
                        lines=context.lines,
                        start_node=block[0],
                        end_node=block[-1],
                    )
                    reported.add(key)
        return storage.diagnostics

    @classmethod
    def _branch_blocks(cls, if_statement: Any) -> list[tuple[Any, ...]]:
        blocks: list[tuple[Any, ...]] = []
        children = _ts_children(if_statement)
        blocks.append(cls._body_after_then(children))
        for child in children:
            child_type = getattr(child, "type", None)
            if child_type == "elseif_clause":
                blocks.append(cls._body_after_then(_ts_children(child)))
            elif child_type == "else_clause":
                blocks.append(cls._body_after_else(_ts_children(child)))
        return blocks

    @classmethod
    def _body_after_then(cls, children: list[Any]) -> tuple[Any, ...]:
        body: list[Any] = []
        in_body = False
        for child in children:
            child_type = getattr(child, "type", None)
            if child_type == "THEN_KEYWORD":
                in_body = True
                continue
            if not in_body:
                continue
            if child_type in {"elseif_clause", "else_clause", "ENDIF_KEYWORD"}:
                break
            if cls._is_code_node(child):
                body.append(child)
        return tuple(body)

    @classmethod
    def _body_after_else(cls, children: list[Any]) -> tuple[Any, ...]:
        body: list[Any] = []
        in_body = False
        for child in children:
            child_type = getattr(child, "type", None)
            if child_type == "ELSE_KEYWORD":
                in_body = True
                continue
            if in_body and cls._is_code_node(child):
                body.append(child)
        return tuple(body)

    @staticmethod
    def _is_code_node(node: Any) -> bool:
        return getattr(node, "type", None) not in {"line_comment", "comment"}

    @staticmethod
    def _block_key(
        block: tuple[Any, ...],
        key_cache: dict[int, tuple[Any, ...]],
    ) -> tuple[Any, ...]:
        return tuple(_structural_node_key(node, key_cache) for node in block)


class DeprecatedCurrentDateRule(DiagnosticRuntimeRule):
    code = "BSL097"
    _names = frozenset({"текущаядата", "currentdate"})
    _message = 'Используйте "ТекущаяДатаСеанса" вместо устаревшего "ТекущаяДата"'

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        root = getattr(context.tree, "root_node", None)
        if root is None:
            return []
        storage = DiagnosticStorage(context.path)
        for call in self._global_method_calls(context):
            if call["name"].casefold() not in self._names:
                continue
            ident = _diag._ts_child_of_type(call["node"], "identifier")
            if ident is None:
                continue
            _add_node_range(
                storage,
                code=self.code,
                message=self._message,
                severity=Severity.ERROR,
                lines=context.lines,
                start_node=ident,
                end_node=ident,
            )
        return storage.diagnostics

    @staticmethod
    def _global_method_calls(context: DiagnosticDocumentContext) -> list[dict[str, Any]]:
        if context.ts_nodes_for_types and context.global_method_calls_from_nodes:
            nodes = context.ts_nodes_for_types(context.tree, {"method_call"})
            return context.global_method_calls_from_nodes(nodes["method_call"], context.lines)
        return _diag._ts_global_method_calls(context.tree.root_node, context.lines)


class ExtraCommasRule(DiagnosticRuntimeRule):
    code = "BSL186"
    _trailing_comma_re = re.compile(r",(?=\s*\))")

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        for idx, line in enumerate(context.lines):
            if _line_comment(line):
                continue
            comment_start = comment_start_outside_double_quotes(line)
            code = line if comment_start is None else line[:comment_start]
            match = self._trailing_comma_re.search(code)
            if match is None:
                continue
            storage.add_range(
                code=self.code,
                line=idx,
                character=match.start(),
                end_line=idx,
                end_character=match.start() + 1,
                severity=Severity.WARNING,
                message="Не используйте запятые для параметров по умолчанию в конце вызова метода.",
            )
        return storage.diagnostics


class YoLetterUsageRule(DiagnosticRuntimeRule):
    code = "BSL279"

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        for idx, line in enumerate(context.lines):
            if _line_comment(line):
                continue
            clean = _code_mask_without_strings_and_comments(line)
            for match in _BSL279_IDENTIFIER_RE.finditer(clean):
                storage.add_range(
                    code=self.code,
                    message='В текстах модулях не допускается использовать букву "Ё".',
                    severity=Severity.INFORMATION,
                    line=idx,
                    character=match.start(),
                    end_line=idx,
                    end_character=match.end(),
                )
        return storage.diagnostics


class QueryJoinDiagnosticsRule(DiagnosticRuntimeRule):
    def __init__(self, code: str):
        self.code = code

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        from onec_hbk_bsl.analysis.diagnostic.rules.query_text_rules import (
            run_bsl206_207_209_query_join_diagnostics,
        )

        query_blocks = context.query_text_blocks
        return run_bsl206_207_209_query_join_diagnostics(
            context.path,
            context.lines,
            (self.code,),
            context.diagnostics_engine._rule_enabled,
            query_blocks,
        )


class QueryTextDiagnosticsRule(DiagnosticRuntimeRule):
    def __init__(self, code: str):
        self.code = code

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        from onec_hbk_bsl.analysis.diagnostic.rules.query_text_rules import (
            run_bsl191_201_query_text_diagnostics,
            run_bsl220_235_269_query_text_diagnostics,
        )

        query_blocks = context.query_text_blocks
        if self.code in {"BSL191", "BSL201"}:
            return run_bsl191_201_query_text_diagnostics(
                context.path,
                context.lines,
                (self.code,),
                context.diagnostics_engine._rule_enabled,
                query_blocks,
            )
        return run_bsl220_235_269_query_text_diagnostics(
            context.path,
            context.lines,
            (self.code,),
            context.diagnostics_engine._rule_enabled,
            query_blocks,
        )


class CommonModuleDiagnosticsRule(DiagnosticRuntimeRule):
    def __init__(self, code: str):
        self.code = code

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        from onec_hbk_bsl.analysis.diagnostic.rules.common_module_rules import (
            run_bsl152_cached_public,
            run_bsl154_code_after_async,
            run_bsl156_code_out_of_region,
            run_bsl158_common_module_assign,
            run_bsl159_common_module_invalid_type,
            run_bsl160_common_module_missing_api,
            run_bsl161_168_common_module_names,
            run_bsl172_data_exchange_loading,
            run_bsl173_deleting_collection_item,
        )

        code = self.code
        procs = context.procedures
        regions = context.regions

        if code == "BSL152":
            return run_bsl152_cached_public(context.path, context.lines, regions, procs)
        if code == "BSL154":
            return run_bsl154_code_after_async(context.path, context.tree)
        if code == "BSL156":
            return run_bsl156_code_out_of_region(context.path, context.lines, procs)
        if code == "BSL158":
            return run_bsl158_common_module_assign(
                context.path,
                context.lines,
                getattr(context.diagnostics_engine, "_symbol_index", None),
            )
        if code == "BSL159":
            return run_bsl159_common_module_invalid_type(context.path, context.lines)
        if code == "BSL160":
            return run_bsl160_common_module_missing_api(context.path, context.lines, regions, procs)
        if code == "BSL172":
            return run_bsl172_data_exchange_loading(context.path, context.lines, procs)
        if code == "BSL173":
            ts_diags = _diagnostics_bsl173_deleting_collection_item(context)
            regex_diags = run_bsl173_deleting_collection_item(context.path, context.lines, procs)
            merged: dict[tuple[int, int], Diagnostic] = {}
            for diag in ts_diags + regex_diags:
                key = (diag.line, diag.character)
                if key not in merged:
                    merged[key] = diag
            return list(merged.values())
        return [
            diag
            for diag in run_bsl161_168_common_module_names(
                context.diagnostics_engine._rule_enabled,
                context.path,
                context.lines,
                (code,),
            )
            if diag.code == code
        ]


class MethodContractDiagnosticsRule(DiagnosticRuntimeRule):
    def __init__(self, code: str):
        self.code = code

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        from onec_hbk_bsl.analysis.diagnostic.rules.method_contract_rules import (
            run_bsl192_193_194_228_266_method_contract_diagnostics,
            run_bsl212_missed_required_parameter,
            run_bsl215_missing_parameter_description,
            run_bsl224_nested_function_in_parameters,
            run_bsl233_public_methods_description,
            run_bsl240_rewrite_method_parameter,
            run_bsl254_transferring_parameters,
        )

        code = self.code
        snapshot = context.snapshot
        procs = context.procedures

        if code in {"BSL192", "BSL193", "BSL194", "BSL228", "BSL266"}:
            return run_bsl192_193_194_228_266_method_contract_diagnostics(
                context.path,
                context.lines,
                procs,
                (code,),
                context.diagnostics_engine._rule_enabled,
            )
        if code == "BSL212":
            calls = list(getattr(snapshot, "calls", []) or [])
            return run_bsl212_missed_required_parameter(
                context.path, context.content, context.lines, procs, calls
            )
        if code == "BSL215":
            return run_bsl215_missing_parameter_description(context.path, context.lines, procs)
        if code == "BSL224":
            nodes_by_type = None
            if context.ts_nodes_for_types is not None:
                nodes_by_type = context.ts_nodes_for_types(
                    context.tree,
                    {"call_expression", "method_call", "new_expression"},
                )
            return run_bsl224_nested_function_in_parameters(
                context.path,
                context.lines,
                context.tree,
                nodes_by_type,
            )
        if code == "BSL233":
            return run_bsl233_public_methods_description(context.path, context.lines, procs)
        if code == "BSL240":
            proc_node_map = dict(getattr(snapshot, "proc_node_map", {}) or {})
            return run_bsl240_rewrite_method_parameter(
                context.path, context.lines, procs, context.tree, proc_node_map
            )
        return run_bsl254_transferring_parameters(
            getattr(context.diagnostics_engine, "_symbol_index", None),
            context.path,
            context.lines,
            procs,
            context.tree,
            dict(getattr(snapshot, "proc_node_map", {}) or {}),
        )


class QueryMetadataDiagnosticsRule(DiagnosticRuntimeRule):
    def __init__(self, code: str):
        self.code = code

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        from onec_hbk_bsl.analysis.diagnostic.rules.query_metadata_rules import (
            run_bsl174_187_236_238_query_metadata_pool,
            run_bsl189_211_213_214_231_232_241_242_246_274_metadata_pool,
            run_bsl244_253_261_runtime_pool,
        )

        code = self.code
        procs = context.procedures
        query_blocks = context.query_text_blocks

        if code in {"BSL174", "BSL187", "BSL236", "BSL238"}:
            return run_bsl174_187_236_238_query_metadata_pool(
                context.path,
                context.lines,
                (code,),
                query_blocks,
                context.lines,
            )
        if code in {"BSL244", "BSL253", "BSL261"}:
            return run_bsl244_253_261_runtime_pool(
                context.path,
                context.lines,
                procs,
                (code,),
                context.lines,
            )
        return run_bsl189_211_213_214_231_232_241_242_246_274_metadata_pool(
            context.path,
            context.lines,
            procs,
            (code,),
            context.lines,
        )


def _run_bsl171_crazy_multiline_string(
    path: str,
    lines: list[str],
    tree: Any | None,
    error_nodes: list[Any] | None = None,
) -> list[Diagnostic]:
    model = ModuleModel(path=path)
    return model.validate_crazy_multiline_string(
        lines=lines,
        tree=tree,
        error_nodes=error_nodes,
        ts_walk_fn=_diag._ts_walk,
        ts_node_text_fn=_diag._ts_node_text,
        utf8_byte_offset_to_lsp_character_fn=utf8_byte_offset_to_lsp_character,
        adjacent_literals_re=_diag._RE_BSL171_ADJACENT_LITERALS,
        rule_descriptions_ru=_diag.RULE_DESCRIPTIONS_RU,
    )


def _run_bsl248_several_compiler_directives(
    path: str,
    lines: list[str],
    tree: Any | None,
    procs: list[Any],
) -> list[Diagnostic]:
    if tree is None:
        return []
    diags: list[Diagnostic] = []
    root = tree.root_node
    children = list(getattr(root, "children", []) or [])
    proc_by_line = {proc.start_idx: proc for proc in procs}

    idx = 0
    while idx < len(children):
        directives: list[Any] = []
        while idx < len(children) and getattr(children[idx], "type", None) == "preprocessor":
            if _diag._ts_node_text(children[idx]).strip().startswith("&"):
                directives.append(children[idx])
            idx += 1
        if idx >= len(children):
            break
        node = children[idx]
        node_type = getattr(node, "type", None)
        if len(directives) > 1 and node_type in {
            "procedure_definition",
            "function_definition",
            "var_definition",
        }:
            if node_type in {"procedure_definition", "function_definition"}:
                proc = proc_by_line.get(node.start_point[0])
                if proc is not None:
                    start_char, end_char = _diag._proc_name_span(lines, proc)
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=proc.start_idx + 1,
                            character=start_char,
                            end_line=proc.start_idx + 1,
                            end_character=end_char,
                            severity=Severity.ERROR,
                            code="BSL248",
                            message=_diag.RULE_DESCRIPTIONS_RU["BSL248"],
                        )
                    )
            else:
                line_idx = node.start_point[0]
                line_text = lines[line_idx] if 0 <= line_idx < len(lines) else ""
                diags.append(
                    Diagnostic(
                        file=path,
                        line=line_idx + 1,
                        character=0,
                        end_line=line_idx + 1,
                        end_character=len(line_text.rstrip()),
                        severity=Severity.ERROR,
                        code="BSL248",
                        message=_diag.RULE_DESCRIPTIONS_RU["BSL248"],
                    )
                )
        idx += 1
    return diags


def _run_bsl251_ternary_operator_usage(
    path: str,
    lines: list[str],
    tree: Any | None,
    ternary_nodes: list[Any] | None = None,
) -> list[Diagnostic]:
    model = ModuleModel(path=path)
    return model.validate_ternary_operator_usage(
        lines=lines,
        tree=tree,
        ternary_nodes=ternary_nodes,
        ts_walk_fn=_diag._ts_walk,
        utf8_byte_offset_to_lsp_character_fn=utf8_byte_offset_to_lsp_character,
        rule_descriptions_ru=_diag.RULE_DESCRIPTIONS_RU,
    )


def _run_bsl252_this_object_assign(
    path: str,
    lines: list[str],
    tree: Any | None,
    assignment_nodes: list[Any] | None = None,
) -> list[Diagnostic]:
    model = ModuleModel(path=path)
    return model.validate_this_object_assign(
        path=path,
        lines=lines,
        tree=tree,
        assignment_nodes=assignment_nodes,
        path_is_likely_form_module_bsl=_diag.path_is_likely_form_module_bsl,
        common_module_path_re=_diag._RE_COMMON_MODULE_PATH,
        ts_walk_fn=_diag._ts_walk,
        ts_child_of_type_fn=_diag._ts_child_of_type,
        ts_node_text_fn=_diag._ts_node_text,
        utf8_byte_offset_to_lsp_character_fn=utf8_byte_offset_to_lsp_character,
        rule_descriptions_ru=_diag.RULE_DESCRIPTIONS_RU,
    )


def _run_bsl259_unknown_preprocessor_symbol(
    path: str,
    lines: list[str],
    tree: Any | None,
    preprocessor_nodes: list[Any] | None = None,
) -> list[Diagnostic]:
    model = ModuleModel(path=path)
    return model.validate_unknown_preprocessor_symbol(
        lines=lines,
        tree=tree,
        preprocessor_nodes=preprocessor_nodes,
        ts_walk_fn=_diag._ts_walk,
        ts_child_of_type_fn=_diag._ts_child_of_type,
        ts_node_text_fn=_diag._ts_node_text,
        utf8_byte_offset_to_lsp_character_fn=utf8_byte_offset_to_lsp_character,
        allowed_preproc_symbols=_diag._BSL259_ALLOWED_PREPROC_SYMBOLS,
        preproc_keywords=_diag._BSL259_PREPROC_KEYWORDS,
        preproc_if_re=_diag._RE_BSL259_PREPROC_IF,
        preproc_identifier_re=_diag._RE_BSL259_IDENTIFIER,
    )


def _run_bsl268_using_find_element_by_string(
    path: str,
    lines: list[str],
    tree: Any | None,
    method_call_nodes: list[Any] | None = None,
) -> list[Diagnostic]:
    model = ModuleModel(path=path)
    return model.validate_using_find_element_by_string(
        lines=lines,
        tree=tree,
        method_call_nodes=method_call_nodes,
        ts_walk_fn=_diag._ts_walk,
        ts_child_of_type_fn=_diag._ts_child_of_type,
        ts_node_text_fn=_diag._ts_node_text,
        ts_method_call_arg_exprs_fn=_diag._ts_method_call_arg_exprs,
        utf8_byte_offset_to_lsp_character_fn=utf8_byte_offset_to_lsp_character,
        method_name_re=_diag._RE_BSL268_FIND_BY_STRING,
        find_matching_paren_fn=_diag._find_matching_paren,
        line_comment_re=_diag._RE_LINE_COMMENT,
        mask_double_quoted_strings_preserve_len_fn=_diag._mask_double_quoted_strings_preserve_len,
    )


class LightPoolDiagnosticsRule(DiagnosticRuntimeRule):
    def __init__(self, code: str):
        self.code = code

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        code = self.code
        engine = context.diagnostics_engine
        snapshot = context.snapshot
        procs = context.procedures
        model = context.module_model

        if code in {"BSL169", "BSL170", "BSL181", "BSL182", "BSL196", "BSL260"}:
            return [
                diag
                for diag in model.validate_bsl169_170_181_182_196_260_light_pool(
                    lines=context.lines,
                    procs=procs,
                    enabled=(code,),
                    snapshot=snapshot,
                    tree=context.tree,
                    ts_nodes_for_types_fn=engine._ts_nodes_for_types,
                    ts_child_of_type_fn=_diag._ts_child_of_type,
                    ts_node_text_fn=_diag._ts_node_text,
                    utf8_byte_offset_to_lsp_character_fn=utf8_byte_offset_to_lsp_character,
                    path_is_likely_form_module_bsl_fn=_diag.path_is_likely_form_module_bsl,
                    path_is_command_module_bsl_fn=_diag._path_is_command_module_bsl,
                    strip_inline_comment_preserve_strings_fn=(
                        _diag._strip_inline_comment_preserve_strings
                    ),
                    line_comment_re=_diag._RE_LINE_COMMENT,
                    proc_name_span_fn=_diag._proc_name_span,
                )
                if diag.code == code
            ]
        if code == "BSL204":
            assert snapshot is not None
            return [
                Diagnostic(
                    file=context.path,
                    line=fact.line_idx + 1,
                    character=fact.character,
                    end_line=fact.line_idx + 1,
                    end_character=fact.end_character,
                    severity=Severity.ERROR,
                    code=code,
                    message=fact.message,
                )
                for fact in snapshot.invalid_character_facts
            ]
        if code in {"BSL171", "BSL248", "BSL251", "BSL252", "BSL259", "BSL268"}:
            return [
                diag
                for diag in model.validate_bsl171_248_251_252_259_268_light_pool(
                    lines=context.lines,
                    tree=context.tree,
                    procs=procs,
                    codes=(code,),
                    rule_enabled_fn=engine._rule_enabled,
                    ts_nodes_for_types_fn=engine._ts_nodes_for_types,
                    rule_bsl171_fn=_run_bsl171_crazy_multiline_string,
                    rule_bsl248_fn=_run_bsl248_several_compiler_directives,
                    rule_bsl251_fn=_run_bsl251_ternary_operator_usage,
                    rule_bsl252_fn=_run_bsl252_this_object_assign,
                    rule_bsl259_fn=_run_bsl259_unknown_preprocessor_symbol,
                    rule_bsl268_fn=_run_bsl268_using_find_element_by_string,
                )
                if diag.code == code
            ]
        if code in {"BSL202", "BSL223", "BSL243", "BSL249"}:
            return [
                diag
                for diag in model.validate_bsl202_205_223_243_249_light_call_pool(
                    lines=context.lines,
                    tree=context.tree,
                    enabled=(code,),
                    snapshot=snapshot,
                    strip_inline_comment_preserve_strings_fn=(
                        _diag._strip_inline_comment_preserve_strings
                    ),
                    ts_nodes_for_types_fn=engine._ts_nodes_for_types,
                    ts_child_of_type_fn=_diag._ts_child_of_type,
                    ts_node_text_fn=_diag._ts_node_text,
                    ts_method_call_arg_exprs_fn=_diag._ts_method_call_arg_exprs,
                    ts_walk_fn=_diag._ts_walk,
                    ts_method_identifier_span_fn=_diag._ts_method_identifier_span,
                    utf8_byte_offset_to_lsp_character_fn=utf8_byte_offset_to_lsp_character,
                    bsl223_structure_names=_diag._BSL223_STRUCTURE_NAMES,
                    bsl249_style_constructor_names=_diag._BSL249_STYLE_CONSTRUCTOR_NAMES,
                    split_top_level_args_fn=_diag._split_top_level_args,
                    find_matching_paren_fn=_diag._find_matching_paren,
                )
                if diag.code == code
            ]
        return [
            diag
            for diag in model.validate_bsl221_222_239_271_light_pool(
                lines=context.lines,
                tree=context.tree,
                procs=procs,
                enabled=(code,),
                snapshot=snapshot,
                strip_inline_comment_preserve_strings_fn=(
                    _diag._strip_inline_comment_preserve_strings
                ),
                reserved_parameter_names_re=engine._reserved_parameter_names_re,
                ts_walk_fn=_diag._ts_walk,
                ts_child_of_type_fn=_diag._ts_child_of_type,
                ts_node_text_fn=_diag._ts_node_text,
                utf8_byte_offset_to_lsp_character_fn=utf8_byte_offset_to_lsp_character,
                bsl221_nstr_re=_diag._RE_BSL221_NSTR,
                bsl221_lang_re=_diag._RE_BSL221_LANG,
                bsl271_unix_unavailable_new_re=_diag._RE_BSL271_UNIX_UNAVAILABLE_NEW,
                bsl271_platform_guard_re=_diag._RE_BSL271_PLATFORM_GUARD,
                proc_name_span_fn=_diag._proc_name_span,
                declared_languages=engine._declared_languages,
            )
            if diag.code == code
        ]


class LocalXmlDiagnosticsRule(DiagnosticRuntimeRule):
    def __init__(self, code: str):
        self.code = code

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        procs = list(getattr(context.snapshot, "procedures", []) or [])
        model = context.module_model
        return [
            diag
            for diag in model.validate_bsl229_275_278_local_xml_pool(
                lines=context.lines,
                procs=procs,
                enabled=(self.code,),
                rule_metadata=_diag.RULE_METADATA,
                severity_cls=Severity,
                proc_name_span_fn=_diag._proc_name_span,
                re_xml_bool_simple=_diag._RE_XML_BOOL_SIMPLE,
                re_bsl275_handler=_diag._RE_BSL275_HANDLER,
                re_bsl278_procname=_diag._RE_BSL278_PROCNAME,
            )
            if diag.code == self.code
        ]


class QueryRuntimeDiagnosticsRule(DiagnosticRuntimeRule):
    def __init__(self, code: str):
        self.code = code

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        from onec_hbk_bsl.analysis.diagnostic.rules.query_runtime_rules import (
            run_bsl234_query_nested_fields_by_dot,
            run_bsl237_redundant_access_to_object,
            run_bsl245_server_side_export_form_method,
        )

        if self.code == "BSL234":
            query_blocks = context.query_text_blocks if context.snapshot is not None else None
            return run_bsl234_query_nested_fields_by_dot(
                context.path,
                context.lines,
                query_blocks,
            )
        if self.code == "BSL237":
            return run_bsl237_redundant_access_to_object(context.path, context.lines)
        procs = list(getattr(context.snapshot, "procedures", []) or [])
        return run_bsl245_server_side_export_form_method(context.path, context.lines, procs)


class MissingSpaceRuntimeRule(DiagnosticRuntimeRule):
    code = "BSL216"

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        assert context.snapshot is not None
        return [
            Diagnostic(
                file=context.path,
                line=fact.line_idx + 1,
                character=fact.character,
                end_line=fact.line_idx + 1,
                end_character=fact.end_character,
                severity=Severity.INFORMATION,
                code=self.code,
                message=fact.message,
            )
            for fact in context.snapshot.missing_space_facts
        ]


class TypoRuntimeRule(DiagnosticRuntimeRule):
    code = "BSL256"

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        if not context.diagnostics_engine._rule_enabled("BSL256"):
            return []
        root = getattr(context.tree, "root_node", None)
        if root is None or not hasattr(root, "text"):
            return []
        if not isinstance(root.text, (bytes, bytearray)):
            return []
        rows = _diag.bslls_typo.spellcheck_typo_diagnostics(
            path=context.path,
            tree=context.tree,
        )
        return [
            Diagnostic(
                file=d["file"],
                line=d["line"],
                character=d["character"],
                end_line=d["end_line"],
                end_character=d["end_character"],
                severity=Severity.INFORMATION,
                code=d["code"],
                message=d["message"],
            )
            for d in rows
        ]


class CoreDiagnosticsRule(DiagnosticRuntimeRule):
    def __init__(self, code: str):
        self.code = code

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        code = self.code
        engine = context.diagnostics_engine
        snapshot = context.snapshot
        procs = context.procedures
        regions = context.regions
        model = context.module_model

        if code == "BSL001":
            return model.validate_bsl001_syntax_errors(
                tree=context.tree,
                parser_extract_errors_fn=engine._get_parser().extract_errors,
                current_lines=getattr(engine, "_current_lines", []),
            )
        if code == "BSL002":
            return model.validate_bsl002_method_size(
                lines=context.lines,
                procs=procs,
                procedure_model_from_proc_info_fn=context.procedure_model_from_proc_info,
                max_proc_lines=engine.max_proc_lines,
                mask_strings_and_comments_for_counter_fn=(
                    _diag._mask_strings_and_comments_for_counter
                ),
                proc_name_span_fn=_diag._proc_name_span,
            )
        if code == "BSL003":
            return model.validate_bsl003_non_export_in_api_region(
                lines=context.lines,
                procs=procs,
                regions=regions,
                api_region_names=_diag._API_REGION_NAMES,
                procedure_model_from_proc_info_fn=context.procedure_model_from_proc_info,
                proc_name_span_fn=_diag._proc_name_span,
            )
        if code == "BSL004":
            from onec_hbk_bsl.analysis.diagnostic.cst import diagnostics_bsl004_from_tree

            if context.tree is None:
                return []
            return diagnostics_bsl004_from_tree(context.path, context.tree.root_node)
        if code == "BSL007":
            return model.validate_bsl007_unused_local_variable(
                lines=context.lines,
                procs=procs,
                snapshot=snapshot,
                strip_inline_comment_preserve_strings_fn=(
                    _diag._strip_inline_comment_preserve_strings
                ),
                bsl007_strip_double_quoted_segments_fn=(_diag._bsl007_strip_double_quoted_segments),
                bsl007_simple_assign_at_start_re=_diag._BSL007_SIMPLE_ASSIGN_AT_START,
                var_local_re=_diag._RE_VAR_LOCAL,
                region_line_re=_diag._RE_REGION_LINE,
                preproc_line_re=_diag._RE_PREPROC_LINE,
                compiler_directive_re=_diag._RE_COMPILER_DIRECTIVE,
                module_assign_re=_diag._RE_MODULE_ASSIGN,
            )
        if code == "BSL008":
            diags: list[Diagnostic] = []
            for proc_model in context.procedure_models:
                diags.extend(
                    proc_model.validate_max_returns(
                        context.lines,
                        max_returns=engine.max_returns,
                        return_re=_diag._RE_RETURN,
                    )
                )
            return diags
        if code == "BSL009":
            if not _diag._ts_tree_ok_for_rules(context.tree):
                return []
            return _diag._diagnostics_bsl009_from_tree(context.path, context.tree.root_node)
        if code == "BSL011":
            diags = []
            metrics = engine._complexity_metrics_for_procs(context.lines, procs)
            for proc_model, (cc, _mc) in zip(context.procedure_models, metrics, strict=False):
                diags.extend(
                    proc_model.validate_cognitive_complexity(
                        cognitive_complexity=cc,
                        max_cognitive_complexity=engine.max_cognitive_complexity,
                        proc_name_span=_diag._proc_name_span,
                        lines=context.lines,
                    )
                )
            return diags
        if code == "BSL012":
            assert snapshot is not None
            return [
                Diagnostic(
                    file=context.path,
                    line=fact.line_idx + 1,
                    character=fact.character,
                    end_line=(fact.end_line_idx if fact.end_line_idx is not None else fact.line_idx)
                    + 1,
                    end_character=fact.end_character,
                    severity=Severity.ERROR,
                    code=code,
                    message=fact.message,
                )
                for fact in snapshot.hardcoded_credential_facts
            ]
        if code == "BSL013":
            assert snapshot is not None
            return [
                Diagnostic(
                    file=context.path,
                    line=fact.line_idx + 1,
                    character=fact.character,
                    end_line=(fact.end_line_idx if fact.end_line_idx is not None else fact.line_idx)
                    + 1,
                    end_character=fact.end_character,
                    severity=Severity.INFORMATION,
                    code=code,
                    message=fact.message,
                )
                for fact in snapshot.commented_code_facts
            ]
        if code == "BSL014":
            assert snapshot is not None
            return [
                Diagnostic(
                    file=context.path,
                    line=fact.line_idx + 1,
                    character=fact.character,
                    end_line=fact.line_idx + 1,
                    end_character=fact.end_character,
                    severity=Severity.INFORMATION,
                    code=code,
                    message=fact.message,
                )
                for fact in snapshot.line_too_long_facts(engine.max_line_length)
            ]
        if code == "BSL015":
            diags = []
            for proc_model in context.procedure_models:
                diags.extend(
                    proc_model.validate_optional_param_limit(
                        context.lines,
                        max_optional_params=engine.max_optional_params,
                    )
                )
            return diags
        if code == "BSL016":
            assert snapshot is not None
            return [
                Diagnostic(
                    file=context.path,
                    line=fact.line_idx + 1,
                    character=fact.character,
                    end_line=fact.line_idx + 1,
                    end_character=fact.end_character,
                    severity=Severity.INFORMATION,
                    code=code,
                    message=fact.message,
                )
                for fact in snapshot.non_standard_region_facts
            ]
        if code == "BSL017":
            if _path_is_split_module_fragment(context.path):
                return []
            assert snapshot is not None
            return [
                Diagnostic(
                    file=context.path,
                    line=fact.line_idx + 1,
                    character=fact.character,
                    end_line=fact.line_idx + 1,
                    end_character=fact.end_character,
                    severity=Severity.WARNING,
                    code=code,
                    message=fact.message,
                )
                for fact in snapshot.command_or_form_export_facts
            ]
        if code == "BSL019":
            diags = []
            metrics = engine._complexity_metrics_for_procs(context.lines, procs)
            for proc_model, (_cog, cc) in zip(context.procedure_models, metrics, strict=False):
                diags.extend(
                    proc_model.validate_mccabe_complexity(
                        mccabe_complexity=cc,
                        max_mccabe_complexity=engine.max_mccabe_complexity,
                        proc_name_span=_diag._proc_name_span,
                        lines=context.lines,
                    )
                )
            return diags
        if code == "BSL020":
            ts_diags = _diagnostics_bsl020_nested_statements(context)
            if ts_diags is not None:
                return ts_diags
            return model.validate_excessive_nesting(
                context.lines,
                procs=procs,
                max_nesting_depth=engine.max_nesting_depth,
            )
        if code == "BSL022":
            assert snapshot is not None
            return [
                Diagnostic(
                    file=context.path,
                    line=fact.line_idx + 1,
                    character=fact.character,
                    end_line=fact.line_idx + 1,
                    end_character=fact.end_character,
                    severity=Severity.WARNING,
                    code=code,
                    message=fact.message,
                )
                for fact in snapshot.deprecated_warning_facts
            ]
        if code == "BSL026":
            if _path_is_split_module_fragment(context.path):
                return []
            assert snapshot is not None
            return [
                Diagnostic(
                    file=context.path,
                    line=fact.line_idx + 1,
                    character=fact.character,
                    end_line=fact.line_idx + 1,
                    end_character=fact.end_character,
                    severity=Severity.INFORMATION,
                    code=code,
                    message=fact.message,
                )
                for fact in snapshot.empty_region_facts
            ]
        if code == "BSL030":
            return _diagnostics_bsl030_semicolon_presence(context)
        if code == "BSL031":
            diags = []
            for proc_model in context.procedure_models:
                diags.extend(
                    proc_model.validate_param_limit(context.lines, max_params=engine.max_params)
                )
            return diags
        if code == "BSL032":
            diags = []
            for proc_model in context.procedure_models:
                diags.extend(
                    proc_model.validate_function_has_return(
                        context.lines,
                        return_re=_diag._RE_RETURN,
                        proc_name_span=_diag._proc_name_span,
                    )
                )
            return diags
        if code == "BSL033":
            loop_lines: set[int] | None = None
            if _diag._ts_tree_ok_for_rules(context.tree):
                loop_lines = _diag.loop_body_line_indices_0(context.tree.root_node)
            diags = []
            for proc_model in context.procedure_models:
                diags.extend(
                    proc_model.validate_query_in_loop(
                        context.lines,
                        loop_lines=loop_lines,
                        loop_open_re=_diag._RE_LOOP_OPEN,
                        loop_close_re=_diag._RE_LOOP_CLOSE,
                    )
                )
            return diags
        if code == "BSL035":
            return model.validate_duplicate_string_literal(
                context.lines,
                procs=procs,
                snapshot=snapshot,
                min_duplicate_uses=engine.min_duplicate_uses,
                string_literal_re=_diag._RE_STRING_LITERAL,
                scope_line_indices_fn=_diag._bsl035_scope_line_indices,
            )
        if code == "BSL036":
            assert snapshot is not None
            return [
                Diagnostic(
                    file=context.path,
                    line=fact.line_idx + 1,
                    character=fact.character,
                    end_line=(fact.end_line_idx if fact.end_line_idx is not None else fact.line_idx)
                    + 1,
                    end_character=fact.end_character,
                    severity=Severity.INFORMATION,
                    code=code,
                    message=fact.message,
                )
                for fact in snapshot.complex_condition_facts(engine.max_bool_ops)
            ]
        if code == "BSL040":
            if _path_is_split_module_fragment(context.path):
                return []
            assert snapshot is not None
            return [
                Diagnostic(
                    file=context.path,
                    line=fact.line_idx + 1,
                    character=fact.character,
                    end_line=fact.line_idx + 1,
                    end_character=fact.end_character,
                    severity=Severity.INFORMATION,
                    code=code,
                    message=fact.message,
                )
                for fact in snapshot.this_form_usage_facts
            ]
        if code == "BSL042":
            return _diagnostics_bsl042_unused_local_method(context)
        if code == "BSL051":
            return model.validate_bsl051_unreachable_code(
                lines=context.lines,
                procs=procs,
                tree=context.tree,
                bsl051_delimiter_lines_for_tree_fn=_diag._bsl051_delimiter_lines_for_tree,
                bsl051_all_branch_exit_end_if_lines_fn=(
                    engine._bsl051_all_branch_exit_end_if_lines
                ),
                re_unconditional_exit=_diag._RE_UNCONDITIONAL_EXIT,
                re_bsl051_delimiter_fallback=_diag._RE_BSL051_DELIMITER_FALLBACK,
            )
        if code == "BSL052":
            return _diagnostics_bsl052_identical_expressions(context)
        if code == "BSL054":
            clean_lines = snapshot.code_lines_without_comments
            return model.validate_module_level_export_variables(
                context.lines,
                procs=procs,
                var_module_export_re=_diag._RE_VAR_MODULE_EXPORT,
                clean_lines=clean_lines,
            )
        if code == "BSL062":
            if _path_is_split_module_fragment(context.path):
                return []
            proc_node_map = dict(getattr(snapshot, "proc_node_map", {}) or {})
            return model.validate_bsl062_unused_parameter(
                lines=context.lines,
                procs=procs,
                tree=context.tree,
                proc_node_map=proc_node_map,
                find_proc_definition_node_fn=_diag._find_proc_definition_node,
                collect_identifier_casefolds_in_proc_body_fn=(
                    _diag._collect_identifier_casefolds_in_proc_body
                ),
                procedure_model_from_proc_info_fn=context.procedure_model_from_proc_info,
            )
        if code == "BSL064":
            proc_node_map = dict(getattr(snapshot, "proc_node_map", {}) or {})
            return model.validate_bsl064_procedure_returns_value(
                procs=procs,
                tree=context.tree,
                proc_node_map=proc_node_map,
                find_proc_definition_node_fn=_diag._find_proc_definition_node,
                ts_walk_fn=_diag._ts_walk,
                utf8_byte_offset_to_lsp_character_fn=(_diag.utf8_byte_offset_to_lsp_character),
                lines=context.lines,
            )
        if code == "BSL065":
            diags = []
            for proc_model in context.procedure_models:
                diags.extend(
                    proc_model.validate_missing_export_comment(
                        context.lines,
                        compiler_directive_re=_diag._RE_COMPILER_DIRECTIVE,
                        bsl215_comment_line_re=_diag._RE_BSL215_COMMENT_LINE,
                    )
                )
            return diags
        if code == "BSL077":
            assert snapshot is not None
            return [
                Diagnostic(
                    file=context.path,
                    line=fact.line_idx + 1,
                    character=fact.character,
                    end_line=fact.line_idx + 1,
                    end_character=fact.end_character,
                    severity=Severity.WARNING,
                    code=code,
                    message=fact.message,
                )
                for fact in snapshot.select_top_without_order_facts
            ]
        if code == "BSL131":
            assert snapshot is not None
            return [
                Diagnostic(
                    file=context.path,
                    line=fact.line_idx + 1,
                    character=fact.character,
                    end_line=fact.line_idx + 1,
                    end_character=fact.end_character,
                    severity=Severity.INFORMATION,
                    code=code,
                    message=fact.message,
                )
                for fact in snapshot.duplicate_region_facts
            ]
        return model.validate_function_paths_return(
            tree=context.tree,
            bsl148_function_name_spans=_diag.bsl148_function_name_spans,
            loops_executed_at_least_once=engine.bsl148_loops_executed_at_least_once,
        )


class DeprecatedApiDiagnosticsRule(DiagnosticRuntimeRule):
    def __init__(self, code: str):
        self.code = code

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        snapshot = context.snapshot
        symbols = list(getattr(snapshot, "symbols", []) or [])
        calls = list(getattr(snapshot, "calls", []) or [])
        model = context.module_model
        return [
            diag
            for diag in model.validate_bsl175_176_177_179_195_deprecated_api_diagnostics(
                lines=context.lines,
                symbols=symbols,
                calls=calls,
                enabled_codes=(self.code,),
                line_comment_re=_diag._RE_LINE_COMMENT,
                bsl176_deprecated_doc_re=_diag._RE_BSL176_DEPRECATED_DOC,
                mask_double_quoted_strings_preserve_len_fn=(
                    _diag._mask_double_quoted_strings_preserve_len
                ),
                bsl175_attribute_re=_diag._RE_BSL175_ATTRIBUTE,
                bsl175_attr_replacements=_diag._BSL175_ATTR_REPLACEMENTS,
                bsl175_method_replacements=_diag._BSL175_METHOD_REPLACEMENTS,
                bsl175_child_form_items_re=_diag._RE_BSL175_CHILD_FORM_ITEMS,
                bsl175_enum_replacements=_diag._BSL175_ENUM_REPLACEMENTS,
                bsl175_enum_name_re=_diag._RE_BSL175_ENUM_NAME,
                bsl175_global_method_re=_diag._RE_BSL175_GLOBAL_METHOD,
                bsl175_global_methods=_diag._BSL175_GLOBAL_METHODS,
            )
            if diag.code == self.code
        ]


class FormDataToValueRule(DiagnosticRuntimeRule):
    code = "BSL190"

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        assert context.snapshot is not None
        return [
            Diagnostic(
                file=context.path,
                line=fact.line_idx + 1,
                character=fact.character,
                end_line=fact.line_idx + 1,
                end_character=fact.end_character,
                severity=Severity.INFORMATION,
                code=self.code,
                message=fact.message,
            )
            for fact in context.snapshot.form_data_to_value_facts
        ]


class LatinCyrillicRuntimeRule(DiagnosticRuntimeRule):
    code = "BSL208"

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        model = context.module_model
        return [
            diag
            for diag in model.validate_bsl208_latin_cyrillic_symbol_in_word(
                lines=context.lines,
                snapshot=context.snapshot,
                rule_enabled_fn=context.diagnostics_engine._rule_enabled,
                re_double_quoted_string=_diag._RE_DOUBLE_QUOTED_STRING,
                re_bsl208_has_latin=_diag._RE_BSL208_HAS_LATIN,
                re_bsl208_has_cyrillic=_diag._RE_BSL208_HAS_CYRILLIC,
                re_bsl208_word=_diag._RE_BSL208_WORD,
                re_bsl208_trailing_lang=_diag._RE_BSL208_TRAILING_LANG,
                bsl208_word_is_standard_tech_name_fn=(_diag._bsl208_word_is_standard_tech_name),
            )
            if diag.code == self.code
        ]


class MissingVariablesDescriptionRule(DiagnosticRuntimeRule):
    code = "BSL219"

    def run(self, context: DiagnosticDocumentContext) -> list[Diagnostic]:
        assert context.snapshot is not None
        return [
            Diagnostic(
                file=context.path,
                line=fact.line_idx + 1,
                character=fact.character,
                end_line=fact.line_idx + 1,
                end_character=fact.end_character,
                severity=Severity.INFORMATION,
                code=self.code,
                message=fact.message,
            )
            for fact in context.snapshot.module_variable_description_facts
        ]
