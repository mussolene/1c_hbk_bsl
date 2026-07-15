"""
Tree-sitter CST helpers and CST-first diagnostic fragments for selected BSL rules.

Contract: use only when :func:`ts_tree_ok_for_rules` is True; otherwise callers
fall back to regex/line heuristics in ``diagnostics.py``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from onec_hbk_bsl.analysis.diagnostic.models import Diagnostic, Severity
from onec_hbk_bsl.analysis.lsp_positions import utf8_byte_offset_to_lsp_character

_TREE_ERROR_CACHE_MAX = 200_000
_tree_error_cache: dict[tuple[int, int, int], bool] = {}


def _tree_error_cache_key(node: Any) -> tuple[int, int, int] | None:
    node_id = getattr(node, "id", None)
    start_byte = getattr(node, "start_byte", None)
    end_byte = getattr(node, "end_byte", None)
    if not all(isinstance(value, int) for value in (node_id, start_byte, end_byte)):
        return None
    return (node_id, start_byte, end_byte)


def tree_has_errors(node: Any) -> bool:
    """True when a tree-sitter subtree contains ERROR or missing nodes."""

    is_missing = getattr(node, "is_missing", False)
    if is_missing:
        return True

    is_error = getattr(node, "is_error", False)
    if is_error:
        return True

    has_error = getattr(node, "has_error", None)
    if isinstance(has_error, bool):
        return has_error

    key = _tree_error_cache_key(node)
    if key is not None:
        cached = _tree_error_cache.get(key)
        if cached is not None:
            return cached

    if node.type in ("ERROR", "error"):
        result = True
    else:
        result = any(tree_has_errors(child) for child in node.children)

    if key is not None:
        if len(_tree_error_cache) >= _TREE_ERROR_CACHE_MAX:
            _tree_error_cache.clear()
        _tree_error_cache[key] = result
    return result


def ts_tree_ok_for_rules(tree: Any) -> bool:
    """True when tree-sitter CST is usable for CST-first rules (no ERROR nodes)."""
    root = getattr(tree, "root_node", None)
    if root is None or not isinstance(getattr(root, "text", None), (bytes, type(None))):
        return False
    return not tree_has_errors(root)


def ts_node_text(node: Any) -> str:
    """Decode tree-sitter node text to str."""
    t = getattr(node, "text", None)
    if t is None:
        return ""
    return t.decode("utf-8", errors="replace") if isinstance(t, bytes) else str(t)


def iter_ts_nodes(node: Any):
    """Yield a tree-sitter subtree in depth-first pre-order.

    ``TreeCursor`` keeps traversal in the native binding and avoids creating a
    Python generator frame for every CST node.  Lightweight test doubles do not
    expose ``walk()``, so they use an iterative stack with identical ordering.
    """
    walk = getattr(node, "walk", None)
    if callable(walk):
        cursor = walk()
        done = False
        while not done:
            yield cursor.node
            if cursor.goto_first_child():
                continue
            while True:
                if cursor.goto_next_sibling():
                    break
                if not cursor.goto_parent():
                    done = True
                    break
        return

    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        children = getattr(current, "children", None) or ()
        stack.extend(reversed(children))


def ts_walk_preorder(
    node: Any,
    visit: Callable[[Any], None],
) -> None:
    """Depth-first pre-order walk."""
    for current in iter_ts_nodes(node):
        visit(current)


def _root_source_lines(node: Any) -> list[str]:
    root = getattr(node, "root_node", None)
    if root is None:
        cur = node
        while getattr(cur, "parent", None) is not None:
            cur = cur.parent
        root = cur
    text = getattr(root, "text", None)
    if isinstance(text, (bytes, bytearray)):
        return text.decode("utf-8", errors="replace").splitlines()
    if isinstance(text, str):
        return text.splitlines()
    return []


def _point_char(lines: list[str], point: Any) -> int:
    line_idx = int(point[0])
    byte_col = int(point[1])
    if 0 <= line_idx < len(lines):
        return utf8_byte_offset_to_lsp_character(lines[line_idx], byte_col)
    return byte_col


def _span_from(node: Any) -> tuple[int, int, int, int]:
    lines = _root_source_lines(node)
    s = node.start_point
    e = node.end_point
    return (
        int(s[0]) + 1,
        _point_char(lines, s),
        int(e[0]) + 1,
        _point_char(lines, e),
    )


def _diag(
    path: str,
    code: str,
    severity: Any,
    message: str,
    node: Any,
) -> Any:
    sev = Severity(severity) if isinstance(severity, str) else severity
    line, ch, end_line, end_ch = _span_from(node)
    return Diagnostic(
        file=path,
        line=line,
        character=ch,
        end_line=end_line,
        end_character=end_ch,
        severity=sev,
        code=code,
    )


def _expr_is_only_string_literal(expr: Any) -> bool:
    if getattr(expr, "type", None) != "expression":
        return False
    ech = [c for c in getattr(expr, "children", []) or [] if c.type != ";"]
    if len(ech) != 1:
        return False
    ce = ech[0]
    if getattr(ce, "type", None) != "const_expression":
        return False
    for c in getattr(ce, "children", []) or []:
        if getattr(c, "type", None) == "string":
            return True
    return False


def ts_clause_body_is_empty(body: list[Any]) -> bool:
    """True if clause body has no executable statements (only comments / bare ``;``)."""
    for c in body:
        ct = getattr(c, "type", None)
        if ct in (None, "line_comment", "block_comment", ";"):
            continue
        return False
    return True


def _bsl004_append_empty_block(
    path: str,
    diags: list[Any],
    anchor_node: Any,
    lines: list[str],
    *,
    end_node: Any | None = None,
) -> None:
    line = anchor_node.start_point[0] + 1
    character = _point_char(lines, anchor_node.start_point)
    end_character = _point_char(lines, (end_node or anchor_node).end_point)
    diags.append(
        Diagnostic(
            file=path,
            line=line,
            character=character,
            end_line=line,
            end_character=max(character + 1, end_character),
            severity=Severity.WARNING,
            code="BSL004",
        )
    )


def _bsl004_append_empty_opening_block(
    path: str,
    diags: list[Any],
    opener_node: Any,
    delimiter_node: Any,
    lines: list[str],
) -> None:
    """Append a diagnostic range for an empty block opener."""
    if opener_node.start_point[0] == delimiter_node.start_point[0]:
        start_point = opener_node.start_point
        end_point = delimiter_node.end_point
    else:
        start_point = delimiter_node.start_point
        end_point = delimiter_node.end_point
    diags.append(
        Diagnostic(
            file=path,
            line=start_point[0] + 1,
            character=_point_char(lines, start_point),
            end_line=end_point[0] + 1,
            end_character=_point_char(lines, end_point),
            severity=Severity.WARNING,
            code="BSL004",
        )
    )


def ts_if_main_then_branch_empty(if_stmt: Any) -> bool:
    """True when the first ``Если`` … ``Тогда`` branch has no executable statements."""
    ch = list(getattr(if_stmt, "children", []) or [])
    if not ch or getattr(ch[0], "type", None) != "IF_KEYWORD":
        return False
    then_index = next(
        (idx for idx, child in enumerate(ch) if getattr(child, "type", None) == "THEN_KEYWORD"),
        None,
    )
    if then_index is None:
        return False
    i = then_index + 1
    start = i
    while i < len(ch) and getattr(ch[i], "type", None) not in (
        "elseif_clause",
        "else_clause",
        "ENDIF_KEYWORD",
    ):
        i += 1
    body = ch[start:i]
    return ts_clause_body_is_empty(body)


def ts_elseif_then_branch_empty(elseif_node: Any) -> bool:
    """True when an ``ИначеЕсли`` … ``Тогда`` branch has no executable statements."""
    ch = list(getattr(elseif_node, "children", []) or [])
    if not ch or getattr(ch[0], "type", None) != "ELSIF_KEYWORD":
        return False
    then_index = next(
        (idx for idx, child in enumerate(ch) if getattr(child, "type", None) == "THEN_KEYWORD"),
        None,
    )
    if then_index is None:
        return False
    body = ch[then_index + 1 :]
    return ts_clause_body_is_empty(body)


def _bsl004_elseif_internal_body(elseif_node: Any) -> list[Any]:
    ch = list(getattr(elseif_node, "children", []) or [])
    for idx, child in enumerate(ch):
        if getattr(child, "type", None) == "THEN_KEYWORD":
            return ch[idx + 1 :]
    return []


def _bsl004_elseif_then_node(elseif_node: Any) -> Any:
    for child in getattr(elseif_node, "children", []) or []:
        if getattr(child, "type", None) == "THEN_KEYWORD":
            return child
    return elseif_node


def _bsl004_else_internal_body(else_node: Any) -> list[Any]:
    ch = list(getattr(else_node, "children", []) or [])
    if ch and getattr(ch[0], "type", None) == "ELSE_KEYWORD":
        return ch[1:]
    return []


def _bsl004_emit_empty_then_for_if_statement(
    if_stmt: Any, path: str, diags: list[Any], lines: list[str]
) -> None:
    ch = list(getattr(if_stmt, "children", []) or [])
    if not ch or getattr(ch[0], "type", None) != "IF_KEYWORD":
        return

    then_index = next(
        (idx for idx, child in enumerate(ch) if getattr(child, "type", None) == "THEN_KEYWORD"),
        None,
    )
    if then_index is None:
        return
    opener_node = ch[0]
    then_node = ch[then_index]
    i = then_index + 1
    start = i
    while i < len(ch) and getattr(ch[i], "type", None) not in (
        "elseif_clause",
        "else_clause",
        "ENDIF_KEYWORD",
    ):
        i += 1
    body = ch[start:i]
    if ts_clause_body_is_empty(body):
        _bsl004_append_empty_opening_block(path, diags, opener_node, then_node, lines)

    while i < len(ch):
        node = ch[i]
        nt = getattr(node, "type", None)
        if nt == "elseif_clause":
            body = _bsl004_elseif_internal_body(node)
            j = i + 1
            if ts_clause_body_is_empty(body):
                opener_node = next(
                    (
                        child
                        for child in getattr(node, "children", []) or []
                        if getattr(child, "type", None) == "ELSIF_KEYWORD"
                    ),
                    node,
                )
                then_node = _bsl004_elseif_then_node(node)
                _bsl004_append_empty_opening_block(path, diags, opener_node, then_node, lines)
            i = j
            continue
        if nt == "else_clause":
            body = _bsl004_else_internal_body(node)
            j = i + 1
            if ts_clause_body_is_empty(body):
                else_keyword = next(
                    (
                        child
                        for child in getattr(node, "children", []) or []
                        if getattr(child, "type", None) == "ELSE_KEYWORD"
                    ),
                    node,
                )
                _bsl004_append_empty_block(path, diags, else_keyword, lines, end_node=else_keyword)
            i = j
            continue
        i += 1


def _bsl004_emit_empty_loop_body(
    loop_node: Any, path: str, diags: list[Any], lines: list[str]
) -> None:
    ch = list(getattr(loop_node, "children", []) or [])
    if not ch:
        return
    do_index = next(
        (idx for idx, child in enumerate(ch) if getattr(child, "type", None) == "DO_KEYWORD"),
        None,
    )
    end_index = next(
        (
            idx
            for idx, child in enumerate(ch)
            if idx > (do_index if do_index is not None else -1)
            and getattr(child, "type", None) == "ENDDO_KEYWORD"
        ),
        None,
    )
    if do_index is None or end_index is None:
        return
    body = ch[do_index + 1 : end_index]
    if not ts_clause_body_is_empty(body):
        return
    opener_node = next(
        (child for child in ch if getattr(child, "type", None) in {"WHILE_KEYWORD", "FOR_KEYWORD"}),
        loop_node,
    )
    _bsl004_append_empty_opening_block(path, diags, opener_node, ch[do_index], lines)


def _try_except_has_only_comments_or_empty(
    try_node: Any,
) -> bool:
    """True if between EXCEPT_KEYWORD and ENDTRY_KEYWORD there are no executable nodes."""
    ch = getattr(try_node, "children", []) or []
    i_except = None
    i_end = None
    for i, c in enumerate(ch):
        if getattr(c, "type", None) == "EXCEPT_KEYWORD":
            i_except = i
        elif getattr(c, "type", None) == "ENDTRY_KEYWORD":
            i_end = i
            break
    if i_except is None or i_end is None or i_end <= i_except:
        return False
    for c in ch[i_except + 1 : i_end]:
        ct = getattr(c, "type", None)
        if ct == "line_comment":
            continue
        if ct != ";":
            return False
    return True


def diagnostics_bsl004_from_tree(
    path: str,
    root: Any,
    lines: list[str] | None = None,
    candidate_nodes: list[Any] | None = None,
) -> list[Any]:
    """BSL004 — empty executable bodies in control-flow branches and loops."""
    diags: list[Any] = []
    source_lines = lines if lines is not None else _root_source_lines(root)

    def visit(node: Any) -> None:
        nt = getattr(node, "type", None)
        if nt == "if_statement":
            _bsl004_emit_empty_then_for_if_statement(node, path, diags, source_lines)
        elif nt in {"while_statement", "for_statement", "for_each_statement"}:
            _bsl004_emit_empty_loop_body(node, path, diags, source_lines)

    if candidate_nodes is None:
        ts_walk_preorder(root, visit)
    else:
        for node in candidate_nodes:
            visit(node)
    return diags


def _else_clause_is_empty(else_node: Any) -> bool:
    ch = [c for c in getattr(else_node, "children", []) or []]
    if not ch:
        return True
    if getattr(ch[0], "type", None) != "ELSE_KEYWORD":
        return False
    rest = ch[1:]
    if not rest:
        return True
    for c in rest:
        if getattr(c, "type", None) != "line_comment":
            return False
    return True


def _loop_body_has_executable(loop_node: Any) -> bool:
    ch = getattr(loop_node, "children", []) or []
    i_do = None
    i_end = None
    for i, c in enumerate(ch):
        if getattr(c, "type", None) == "DO_KEYWORD":
            i_do = i
        elif getattr(c, "type", None) == "ENDDO_KEYWORD":
            i_end = i
            break
    if i_do is None or i_end is None or i_end <= i_do:
        return True
    for c in ch[i_do + 1 : i_end]:
        ct = getattr(c, "type", None)
        if ct == "line_comment":
            continue
        if ct != ";":
            return True
    return False


def loop_body_line_indices_0(root: Any) -> set[int]:
    """
    0-based line indices of any source line strictly inside a loop body
    (between ``DO`` and ``ENDDO``), excluding the ``DO``/``ENDDO`` lines.
    """
    lines: set[int] = set()

    def visit(node: Any) -> None:
        nt = getattr(node, "type", None)
        if nt not in ("while_statement", "for_statement", "for_each_statement"):
            return
        ch = getattr(node, "children", []) or []
        i_do = None
        i_end = None
        for i, c in enumerate(ch):
            if getattr(c, "type", None) == "DO_KEYWORD":
                i_do = i
            elif getattr(c, "type", None) == "ENDDO_KEYWORD":
                i_end = i
                break
        if i_do is None or i_end is None or i_end <= i_do:
            return
        for c in ch[i_do + 1 : i_end]:
            s0 = c.start_point[0]
            s1 = c.end_point[0]
            for li in range(s0, s1 + 1):
                lines.add(li)

    ts_walk_preorder(root, visit)
    return lines
