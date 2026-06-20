from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from onec_hbk_bsl.analysis.diagnostic.helpers.config_helpers import current_form_xml_path
from onec_hbk_bsl.analysis.diagnostic.rules.module_structure_rules import (
    is_split_module_fragment,
)
from onec_hbk_bsl.analysis.sdbl_cst import QUERY_METADATA_ROOTS


def _diag_module() -> Any:
    from onec_hbk_bsl.analysis import diagnostics as _diag

    return _diag


def _node_text(node: Any) -> str:
    text = getattr(node, "text", b"")
    if isinstance(text, bytes):
        return text.decode("utf-8", errors="replace")
    return str(text)


def _iter_nodes(node: Any, node_type: str):
    if getattr(node, "type", None) == node_type:
        yield node
    for child in getattr(node, "children", []) or []:
        yield from _iter_nodes(child, node_type)


def _field_has_alias(field_node: Any) -> bool:
    for child in getattr(field_node, "children", []) or []:
        if getattr(child, "type", None) != "field_alias":
            continue
        child_types = {getattr(grandchild, "type", None) for grandchild in child.children}
        return "AS_KEYWORD" in child_types and "identifier" in child_types
    return False


def _inside_union_clause(node: Any) -> bool:
    parent = getattr(node, "parent", None)
    while parent is not None:
        if getattr(parent, "type", None) == "union_clause":
            return True
        parent = getattr(parent, "parent", None)
    return False


def _ancestor_of_type(node: Any, node_type: str) -> Any | None:
    parent = getattr(node, "parent", None)
    while parent is not None:
        if getattr(parent, "type", None) == node_type:
            return parent
        parent = getattr(parent, "parent", None)
    return None


def _field_belongs_to_select_list(field_node: Any) -> bool:
    return getattr(getattr(field_node, "parent", None), "type", None) == "field_list"


def _query_has_from_clause(field_node: Any) -> bool:
    query = _ancestor_of_type(field_node, "query")
    if query is None:
        return False
    return any(
        getattr(node, "type", None) == "from_clause" for node in _iter_nodes(query, "from_clause")
    )


def _field_should_be_skipped(field_text: str) -> bool:
    stripped = field_text.strip().rstrip(";")
    if not stripped or stripped == "*" or re.match(r"^\w+\.\*$", stripped, re.UNICODE):
        return True
    if stripped.startswith('""'):
        return True
    return False


def _query_block_has_dynamic_tail(lines: list[str], block: Any) -> bool:
    content_lines = list(getattr(block, "content_lines", []) or [])
    if not content_lines or not getattr(content_lines[-1], "ended_query", False):
        return False
    next_idx = content_lines[-1].line_no
    while next_idx < len(lines) and not lines[next_idx].strip():
        next_idx += 1
    return next_idx < len(lines) and lines[next_idx].lstrip().startswith("+")


def _query_block_is_dynamic_fragment(block: Any) -> bool:
    query_text = str(getattr(block, "query_text", "") or "")
    return bool(
        re.match(
            r"^\s*(?:ОБЪЕДИНИТЬ|UNION|И|AND|ИЛИ|OR)\b",
            query_text,
            re.IGNORECASE,
        )
    )


def _run_bsl149_on_sdbl_tree(path: str, lines: list[str], block: Any) -> list[Any]:
    tree = getattr(block, "sdbl_tree", None)
    root = getattr(tree, "root_node", None)
    if root is None or _query_block_has_dynamic_tail(lines, block):
        return []
    if getattr(block, "sdbl_has_errors", False) and _query_block_is_dynamic_fragment(block):
        return []

    _diag = _diag_module()
    diags: list[Any] = []
    for field_node in _iter_nodes(root, "field"):
        if not _field_belongs_to_select_list(field_node):
            continue
        if not _query_has_from_clause(field_node):
            continue
        if _inside_union_clause(field_node):
            continue
        if _field_has_alias(field_node):
            continue
        field_text = _node_text(field_node)
        if _field_should_be_skipped(field_text):
            continue
        start_line, start_char = block.original_lsp_position(
            field_node.start_point[0], field_node.start_point[1]
        )
        end_line, end_char = block.original_lsp_position(
            field_node.end_point[0], field_node.end_point[1]
        )
        diags.append(
            _diag.Diagnostic(
                file=path,
                line=start_line + 1,
                character=start_char,
                end_line=end_line + 1,
                end_character=end_char,
                severity=_diag.Severity.WARNING,
                code="BSL149",
            )
        )
    return diags


def _run_bsl149_on_query_blocks(path: str, lines: list[str], query_blocks: list[Any]) -> list[Any]:
    diags: list[Any] = []
    for block in query_blocks:
        if _query_block_has_dynamic_tail(lines, block):
            continue
        diags.extend(_run_bsl149_on_sdbl_tree(path, lines, block))
    return diags


def run_bsl149_assign_alias_fields_in_query(
    path: str, lines: list[str], query_blocks: list[Any] | None = None
) -> list[Any]:
    if query_blocks is not None:
        return _run_bsl149_on_query_blocks(path, lines, query_blocks)
    return []


def run_bsl234_query_nested_fields_by_dot(
    path: str, lines: list[str], query_blocks: list[Any] | None = None
) -> list[Any]:
    _diag = _diag_module()
    diags: list[Any] = []
    chain_re = re.compile(r"(?<![\w.])([A-Za-zА-Яа-я_]\w*(?:\.[A-Za-zА-Яа-я_]\w*){2,})")
    cast_field_re = re.compile(
        r"(?:ВЫРАЗИТЬ|CAST)\s*\(\s*([A-Za-zА-Яа-я_]\w*\.[A-Za-zА-Яа-я_]\w*)\s+"
        r"(?:КАК|AS)\b[^)]*\)\s*\.[A-Za-zА-Яа-я_]\w*",
        re.IGNORECASE,
    )
    cast_nested_field_re = re.compile(
        r"(?:ВЫРАЗИТЬ|CAST)\s*\([^)]*\)\s*\.[A-Za-zА-Яа-я_]\w*\.[A-Za-zА-Яа-я_]\w*",
        re.IGNORECASE,
    )
    one_dot_chain_re = re.compile(r"(?<![\w.])([A-Za-zА-Яа-я_]\w*\.[A-Za-zА-Яа-я_]\w*)(?![\w.])")
    value_re = re.compile(r"(?:ЗНАЧЕНИЕ|VALUE)\s*\(", re.IGNORECASE)

    def mask_value_calls(text: str) -> str:
        chars = list(text)
        pos = 0
        while True:
            match = value_re.search(text, pos)
            if match is None:
                break
            depth = 0
            end = match.end()
            while end < len(text):
                ch = text[end]
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    if depth == 0:
                        end += 1
                        break
                    depth -= 1
                end += 1
            for idx in range(match.start(), min(end, len(chars))):
                chars[idx] = " "
            pos = end
        return "".join(chars)

    seen: set[tuple[int, int, str]] = set()
    in_group_by = False
    in_where = False

    def add_diag(line_no: int, start: int, end: int) -> None:
        key = (line_no, start, "BSL234")
        if key in seen:
            return
        seen.add(key)
        diags.append(
            _diag.Diagnostic(
                file=path,
                line=line_no,
                character=start,
                end_line=line_no,
                end_character=end,
                severity=_diag.Severity.WARNING,
                code="BSL234",
            )
        )

    if query_blocks is None:
        return []
    content_lines = [
        (line_no, lines[line_no - 1], head)
        for block in query_blocks
        for (
            line_no,
            _content_base,
            _content,
            head,
            _ended_query,
        ) in _diag._query_block_content_line_tuples(block)
    ]

    for line_no, line, query_text in content_lines:
        if not query_text:
            in_group_by = False
            in_where = False
            continue
        masked = mask_value_calls(line)
        if re.match(r"^(?:ВЫБРАТЬ|SELECT)\b", query_text, re.IGNORECASE):
            in_group_by = False
            in_where = False
        if re.match(r"^(?:СГРУППИРОВАТЬ\s+ПО|GROUP\s+BY)\b", query_text, re.IGNORECASE):
            in_group_by = True
            in_where = False
            continue
        if re.match(r"^(?:ГДЕ|WHERE)\b", query_text, re.IGNORECASE):
            in_where = True
            in_group_by = False
            continue
        if re.match(
            r"^(?:ИЗ|FROM|УПОРЯДОЧИТЬ\s+ПО|ORDER\s+BY|ИТОГИ|TOTALS|;)\b",
            query_text,
            re.IGNORECASE,
        ):
            in_group_by = False
            in_where = False

        if in_where:
            for match in cast_field_re.finditer(masked):
                add_diag(line_no, match.start(1), match.end(1))

        for match in cast_nested_field_re.finditer(masked):
            add_diag(line_no, match.start(0), match.end(0))

        if re.search(r"\)\s+(?:В|IN)\b", masked, re.IGNORECASE):
            for match in one_dot_chain_re.finditer(masked):
                root = match.group(1).split(".", 1)[0].casefold()
                if root in QUERY_METADATA_ROOTS:
                    continue
                add_diag(line_no, match.start(1), match.end(1))

        if in_group_by:
            for match in one_dot_chain_re.finditer(masked):
                root = match.group(1).split(".", 1)[0].casefold()
                if not ("обороты" in root or "turnovers" in root):
                    continue
                trailing = masked[match.end(1) :]
                if re.match(r"^\s+(?:КАК|AS)\b", trailing, re.IGNORECASE):
                    continue
                add_diag(line_no, match.start(1), match.end(1))

        for match in chain_re.finditer(masked):
            chain = match.group(1)
            trailing = masked[match.end(1) :]
            if re.match(r"^\s+(?:КАК|AS)\b", trailing, re.IGNORECASE):
                first = chain.split(".", 1)[0].casefold()
                if first in QUERY_METADATA_ROOTS:
                    continue
            if re.match(r"^\s*\(", trailing):
                continue
            add_diag(line_no, match.start(1), match.end(1))
    return diags


def run_bsl237_redundant_access_to_object(path: str, lines: list[str]) -> list[Any]:
    _diag = _diag_module()
    low = path.replace("\\", "/").lower()
    supported = (
        low.endswith("/ext/objectmodule.bsl")
        or low.endswith("/ext/recordsetmodule.bsl")
        or low.endswith("/ext/managermodule.bsl")
        or _diag.path_is_likely_form_module_bsl(path)
        or low.endswith("/ext/module.bsl")
    )
    if not supported:
        return []

    diags: list[Any] = []
    patterns = _diag._redundant_access_prefix_patterns(path)
    for line_no, line in enumerate(lines, start=1):
        if _diag._RE_LINE_COMMENT.match(line):
            continue
        clean = _diag._mask_double_quoted_strings_preserve_len(line)
        comment_pos = clean.find("//")
        if comment_pos >= 0:
            clean = clean[:comment_pos]
        for pattern in patterns:
            for match in pattern.finditer(clean):
                tail = clean[match.end() :]
                if re.match(r"\s*\w+\s*\(", tail, re.IGNORECASE | re.UNICODE):
                    continue
                diags.append(
                    _diag.Diagnostic(
                        file=path,
                        line=line_no,
                        character=match.start(),
                        end_line=line_no,
                        end_character=match.end() - 1,
                        severity=_diag.Severity.INFORMATION,
                        code="BSL237",
                    )
                )
    return diags


def run_bsl245_server_side_export_form_method(
    path: str, lines: list[str], procs: list[Any]
) -> list[Any]:
    _diag = _diag_module()
    if is_split_module_fragment(path) or not _diag.path_is_likely_form_module_bsl(path):
        return []
    if _path_is_known_ordinary_form_module(path):
        return []
    diags: list[Any] = []
    for proc in procs:
        if not proc.is_export:
            continue
        if _diag._procedure_compiler_execution_context(lines, proc) == "client":
            continue
        start_char, end_char = _diag._proc_name_span(lines, proc)
        diags.append(
            _diag.Diagnostic(
                file=path,
                line=proc.start_idx + 1,
                character=start_char,
                end_line=proc.start_idx + 1,
                end_character=end_char,
                severity=_diag.Severity.ERROR,
                code="BSL245",
            )
        )
    return diags


def _path_is_known_ordinary_form_module(path: str) -> bool:
    module_path = Path(path)
    xml_path = current_form_xml_path(path)
    candidates: list[Path] = []
    if xml_path is not None:
        candidates.append(xml_path)
    candidates.extend(
        [
            module_path.parent / "Form.xml",
            module_path.parent / "form.xml",
            module_path.parent.parent / "Form.xml",
            module_path.parent.parent / "form.xml",
        ]
    )
    raw = ""
    for candidate in candidates:
        try:
            raw = candidate.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
        if raw:
            break
    if raw:
        if re.search(r"<FormType>\s*(?:Ordinary|Обыч\w*)\s*</FormType>", raw, re.IGNORECASE):
            return True
        if re.search(r"<UseManagedForm>\s*false\s*</UseManagedForm>", raw, re.IGNORECASE):
            return True
        return bool(re.search(r"<Managed>\s*false\s*</Managed>", raw, re.IGNORECASE))
    low = path.replace("\\", "/").lower()
    return "/forms/" in low and low.endswith("/ext/module.bsl")
