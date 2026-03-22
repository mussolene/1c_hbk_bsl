"""
Tree-sitter CST helpers and CST-first diagnostic fragments for selected BSL rules.

Contract: use only when :func:`ts_tree_ok_for_rules` is True; otherwise callers
fall back to regex/line heuristics in ``diagnostics.py``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from onec_hbk_bsl.analysis.formatter_structural import tree_has_errors


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


def ts_walk_preorder(
    node: Any,
    visit: Callable[[Any], None],
) -> None:
    """Depth-first pre-order walk."""
    visit(node)
    for c in getattr(node, "children", []) or []:
        ts_walk_preorder(c, visit)


def _span_from(node: Any) -> tuple[int, int, int, int]:
    s = node.start_point
    e = node.end_point
    return (s[0] + 1, s[1], e[0] + 1, e[1])


def _diag(
    path: str,
    code: str,
    severity: Any,
    message: str,
    node: Any,
) -> Any:
    from onec_hbk_bsl.analysis.diagnostics import Diagnostic, Severity

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
        message=message,
    )


def _unary_operator_text(node: Any) -> str:
    for c in getattr(node, "children", []) or []:
        if getattr(c, "type", None) == "operator":
            return ts_node_text(c).strip().lower()
    return ""


def _is_not_negation(node: Any) -> bool:
    return getattr(node, "type", None) == "unary_expression" and _unary_operator_text(
        node
    ) in ("не", "not")


def _double_negation_span(node: Any) -> tuple[int, int, int, int] | None:
    """
    If *node* is unary_expression NOT NOT …, return span covering both operators
    (the minimal ``НЕ НЕ`` sub-span).
    """
    if not _is_not_negation(node):
        return None
    ch = getattr(node, "children", []) or []
    inner_expr = None
    for c in ch:
        if getattr(c, "type", None) == "expression":
            inner_expr = c
            break
    if inner_expr is None:
        return None
    inner_ch = getattr(inner_expr, "children", []) or []
    if len(inner_ch) != 1:
        return None
    child = inner_ch[0]
    if not _is_not_negation(child):
        return None
    # Span: first operator of outer node to end of inner unary's operator
    outer_op = next(
        (c for c in ch if getattr(c, "type", None) == "operator"),
        None,
    )
    inner_ch2 = getattr(child, "children", []) or []
    inner_op = next(
        (c for c in inner_ch2 if getattr(c, "type", None) == "operator"),
        None,
    )
    if outer_op is None or inner_op is None:
        return None
    s = outer_op.start_point
    e = inner_op.end_point
    return (s[0] + 1, s[1], e[0] + 1, e[1])


def diagnostics_bsl060_from_tree(path: str, root: Any) -> list[Any]:
    """BSL060 — double negation ``НЕ НЕ`` / ``Not Not``."""
    from onec_hbk_bsl.analysis.diagnostics import Diagnostic, Severity

    diags: list[Any] = []
    seen: set[tuple[int, int, int, int]] = set()

    def visit(node: Any) -> None:
        if getattr(node, "type", None) != "unary_expression":
            return
        span = _double_negation_span(node)
        if span is None:
            return
        if span in seen:
            return
        seen.add(span)
        line, ch, end_line, end_ch = span
        diags.append(
            Diagnostic(
                file=path,
                line=line,
                character=ch,
                end_line=end_line,
                end_character=end_ch,
                severity=Severity.INFORMATION,
                code="BSL060",
                message=(
                    "Double negation 'НЕ НЕ ...' — "
                    "the two negations cancel out; use the expression directly."
                ),
            )
        )

    ts_walk_preorder(root, visit)
    return diags


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


def diagnostics_bsl018_from_tree(path: str, root: Any) -> list[Any]:
    """BSL018 — ``ВызватьИсключение`` with only a string literal (no extended args)."""
    from onec_hbk_bsl.analysis.diagnostics import Severity

    diags: list[Any] = []

    def visit(node: Any) -> None:
        if getattr(node, "type", None) != "rise_error_statement":
            return
        has_args = any(
            getattr(c, "type", None) == "arguments" for c in getattr(node, "children", []) or []
        )
        if has_args:
            return
        expr = None
        for c in getattr(node, "children", []) or []:
            if getattr(c, "type", None) == "expression":
                expr = c
                break
        if expr is None or not _expr_is_only_string_literal(expr):
            return
        diags.append(_diag(path, "BSL018", Severity.WARNING, (
            "ВызватьИсключение used with only a string literal. "
            "For structured error data, use the extended "
            "ВызватьИсключение(...); syntax (8.3.21+) or build the text "
            "in a variable/expression."
        ), expr))

    ts_walk_preorder(root, visit)
    return diags


def _literal_boolean_from_if_expression(expr: Any) -> str | None:
    """Same as BSL052: single boolean literal in expression."""
    if getattr(expr, "type", None) != "expression":
        return None
    meaningful = [c for c in getattr(expr, "children", []) or [] if c.type not in (";",)]
    if len(meaningful) != 1:
        return None
    child = meaningful[0]
    if getattr(child, "type", None) != "const_expression":
        return None
    for c in getattr(child, "children", []) or []:
        if getattr(c, "type", None) != "boolean":
            continue
        for bc in getattr(c, "children", []) or []:
            if getattr(bc, "type", None) in ("TRUE_KEYWORD", "FALSE_KEYWORD"):
                return ts_node_text(bc)
    return None


def diagnostics_bsl085_from_tree(path: str, root: Any, lines: list[str]) -> list[Any]:
    """BSL085 — literal boolean in ``Если`` / ``ИначеЕсли`` condition (with ``Тогда``)."""
    from onec_hbk_bsl.analysis.diagnostics import Diagnostic, Severity

    diags: list[Any] = []

    def _from_if_like(node: Any) -> None:
        keyword_line: int | None = None
        for c in getattr(node, "children", []) or []:
            ct = getattr(c, "type", None)
            if ct in ("IF_KEYWORD", "ELSIF_KEYWORD"):
                keyword_line = c.start_point[0]
            elif ct == "expression":
                lit = _literal_boolean_from_if_expression(c)
                if lit is not None and keyword_line is not None:
                    li = keyword_line
                    line_text = lines[li] if li < len(lines) else ""
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=li + 1,
                            character=len(line_text) - len(line_text.lstrip()),
                            end_line=li + 1,
                            end_character=len(line_text.rstrip()),
                            severity=Severity.WARNING,
                            code="BSL085",
                            message=(
                                "Condition is a literal boolean — the branch always or never executes. "
                                "Remove the dead code or fix the condition."
                            ),
                        )
                    )
                return
            elif ct == "THEN_KEYWORD":
                break

    def walk(node: Any) -> None:
        if getattr(node, "type", None) in ("if_statement", "elseif_clause"):
            _from_if_like(node)
        for c in getattr(node, "children", []) or []:
            walk(c)

    walk(root)
    return diags


def ts_clause_body_is_empty(body: list[Any]) -> bool:
    """True if clause body has no executable statements (only comments / bare ``;``)."""
    for c in body:
        ct = getattr(c, "type", None)
        if ct in (None, "line_comment", ";"):
            continue
        return False
    return True


def _bsl004_append_empty_block(
    path: str,
    diags: list[Any],
    anchor_kw: Any,
    message: str,
) -> None:
    from onec_hbk_bsl.analysis.diagnostics import Diagnostic, Severity

    diags.append(
        Diagnostic(
            file=path,
            line=anchor_kw.start_point[0] + 1,
            character=anchor_kw.start_point[1],
            end_line=anchor_kw.end_point[0] + 1,
            end_character=anchor_kw.end_point[1],
            severity=Severity.WARNING,
            code="BSL004",
            message=message,
        )
    )


def _bsl004_emit_empty_then_for_elseif_clause(
    elseif_node: Any, path: str, diags: list[Any], empty_msg: str
) -> None:
    ech = list(getattr(elseif_node, "children", []) or [])
    j = 0
    if j < len(ech) and getattr(ech[j], "type", None) == "ELSIF_KEYWORD":
        j += 1
    else:
        return
    if j < len(ech) and getattr(ech[j], "type", None) == "expression":
        j += 1
    if j >= len(ech) or getattr(ech[j], "type", None) != "THEN_KEYWORD":
        return
    then_kw = ech[j]
    j += 1
    body = ech[j:]
    if not ts_clause_body_is_empty(body):
        return
    _bsl004_append_empty_block(path, diags, then_kw, empty_msg)


def ts_if_main_then_branch_empty(if_stmt: Any) -> bool:
    """True when the first ``Если`` … ``Тогда`` branch has no executable statements."""
    ch = list(getattr(if_stmt, "children", []) or [])
    i = 0
    if i < len(ch) and getattr(ch[i], "type", None) == "IF_KEYWORD":
        i += 1
    else:
        return False
    if i < len(ch) and getattr(ch[i], "type", None) == "expression":
        i += 1
    if i >= len(ch) or getattr(ch[i], "type", None) != "THEN_KEYWORD":
        return False
    i += 1
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
    ech = list(getattr(elseif_node, "children", []) or [])
    j = 0
    if j < len(ech) and getattr(ech[j], "type", None) == "ELSIF_KEYWORD":
        j += 1
    else:
        return False
    if j < len(ech) and getattr(ech[j], "type", None) == "expression":
        j += 1
    if j >= len(ech) or getattr(ech[j], "type", None) != "THEN_KEYWORD":
        return False
    j += 1
    body = ech[j:]
    return ts_clause_body_is_empty(body)


def _bsl004_emit_empty_then_for_if_statement(
    if_stmt: Any, path: str, diags: list[Any], empty_msg: str
) -> None:
    ch = list(getattr(if_stmt, "children", []) or [])
    i = 0
    if i < len(ch) and getattr(ch[i], "type", None) == "IF_KEYWORD":
        i += 1
    else:
        return
    if i < len(ch) and getattr(ch[i], "type", None) == "expression":
        i += 1
    if i >= len(ch) or getattr(ch[i], "type", None) != "THEN_KEYWORD":
        return
    then_kw = ch[i]
    i += 1
    start = i
    while i < len(ch) and getattr(ch[i], "type", None) not in (
        "elseif_clause",
        "else_clause",
        "ENDIF_KEYWORD",
    ):
        i += 1
    body = ch[start:i]
    if ts_clause_body_is_empty(body):
        _bsl004_append_empty_block(path, diags, then_kw, empty_msg)
    while i < len(ch):
        if getattr(ch[i], "type", None) == "elseif_clause":
            _bsl004_emit_empty_then_for_elseif_clause(ch[i], path, diags, empty_msg)
        i += 1


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


def diagnostics_bsl004_from_tree(path: str, root: Any) -> list[Any]:
    """BSL004 — empty code blocks (BSLLS ``EmptyCodeBlock``): empty Except, empty Тогда."""
    from onec_hbk_bsl.analysis.diagnostics import Diagnostic, Severity

    diags: list[Any] = []
    empty_then_msg = (
        "Empty code block: 'Тогда' branch contains no statements — "
        "add logic or remove the branch."
    )

    def visit(node: Any) -> None:
        nt = getattr(node, "type", None)
        if nt == "try_statement":
            if not _try_except_has_only_comments_or_empty(node):
                return
            for c in getattr(node, "children", []) or []:
                if getattr(c, "type", None) == "EXCEPT_KEYWORD":
                    line = c.start_point[0] + 1
                    diags.append(
                        Diagnostic(
                            file=path,
                            line=line,
                            character=0,
                            end_line=line,
                            end_character=0,
                            severity=Severity.WARNING,
                            code="BSL004",
                            message=(
                                "Empty exception handler: Except block contains no statements. "
                                "Add error handling or at least a comment explaining why "
                                "it is intentionally empty."
                            ),
                        )
                    )
                    return
        elif nt == "if_statement":
            _bsl004_emit_empty_then_for_if_statement(node, path, diags, empty_then_msg)

    ts_walk_preorder(root, visit)
    return diags


def _if_clause_last_statement_is_return(clause_children: list[Any]) -> bool:
    """Statements in ``Если``/``ИначеЕсли`` branch after ``Тогда``."""
    stmts = [
        c
        for c in clause_children
        if getattr(c, "type", None) not in ("line_comment", ";")
        and getattr(c, "type", None) is not None
    ]
    if not stmts:
        return False
    return getattr(stmts[-1], "type", None) == "return_statement"


def _emit_bsl091_else(else_node: Any, path: str, diags: list[Any]) -> None:
    from onec_hbk_bsl.analysis.diagnostics import Diagnostic, Severity

    else_kw = next(
        (c for c in getattr(else_node, "children", []) or [] if c.type == "ELSE_KEYWORD"),
        else_node,
    )
    diags.append(
        Diagnostic(
            file=path,
            line=else_kw.start_point[0] + 1,
            character=else_kw.start_point[1],
            end_line=else_kw.end_point[0] + 1,
            end_character=else_kw.end_point[1],
            severity=Severity.INFORMATION,
            code="BSL091",
            message=(
                "Иначе/Else after Возврат/Return is redundant — "
                "remove Иначе and dedent the block."
            ),
        )
    )


def diagnostics_bsl091_from_tree(path: str, root: Any) -> list[Any]:
    """BSL091 — redundant ``Иначе`` after ``Возврат`` in the same branch."""
    diags: list[Any] = []

    def process_if_statement(node: Any) -> None:
        ch = list(getattr(node, "children", []) or [])
        i = 0
        if i < len(ch) and getattr(ch[i], "type", None) == "IF_KEYWORD":
            i += 1
        else:
            return
        if i < len(ch) and getattr(ch[i], "type", None) == "expression":
            i += 1
        if i < len(ch) and getattr(ch[i], "type", None) == "THEN_KEYWORD":
            i += 1
        start = i
        while i < len(ch) and getattr(ch[i], "type", None) not in (
            "elseif_clause",
            "else_clause",
            "ENDIF_KEYWORD",
        ):
            i += 1
        body = ch[start:i]
        if _if_clause_last_statement_is_return(body) and i < len(ch):
            if getattr(ch[i], "type", None) == "else_clause":
                _emit_bsl091_else(ch[i], path, diags)
        while i < len(ch):
            c = ch[i]
            if getattr(c, "type", None) == "elseif_clause":
                ech = list(getattr(c, "children", []) or [])
                j = 0
                if j < len(ech) and getattr(ech[j], "type", None) == "ELSIF_KEYWORD":
                    j += 1
                if j < len(ech) and getattr(ech[j], "type", None) == "expression":
                    j += 1
                if j < len(ech) and getattr(ech[j], "type", None) == "THEN_KEYWORD":
                    j += 1
                ebody = ech[j:]
                if _if_clause_last_statement_is_return(ebody) and i + 1 < len(ch):
                    if getattr(ch[i + 1], "type", None) == "else_clause":
                        _emit_bsl091_else(ch[i + 1], path, diags)
                i += 1
                continue
            i += 1

    def walk(node: Any) -> None:
        if getattr(node, "type", None) == "if_statement":
            process_if_statement(node)
        for c in getattr(node, "children", []) or []:
            walk(c)

    walk(root)
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


def diagnostics_bsl092_from_tree(path: str, root: Any) -> list[Any]:
    """BSL092 — empty ``Иначе`` block."""
    from onec_hbk_bsl.analysis.diagnostics import Diagnostic, Severity

    diags: list[Any] = []

    def visit(node: Any) -> None:
        if getattr(node, "type", None) != "else_clause":
            return
        if not _else_clause_is_empty(node):
            return
        else_kw = next(
            (c for c in getattr(node, "children", []) or [] if c.type == "ELSE_KEYWORD"),
            node,
        )
        diags.append(
            Diagnostic(
                file=path,
                line=else_kw.start_point[0] + 1,
                character=else_kw.start_point[1],
                end_line=else_kw.end_point[0] + 1,
                end_character=else_kw.end_point[1],
                severity=Severity.WARNING,
                code="BSL092",
                message=(
                    "Empty Иначе/Else block — remove it or add a comment "
                    "explaining why it is intentionally empty."
                ),
            )
        )

    ts_walk_preorder(root, visit)
    return diags


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


def diagnostics_bsl070_from_tree(path: str, root: Any) -> list[Any]:
    """BSL070 — empty loop body."""
    from onec_hbk_bsl.analysis.diagnostics import Diagnostic, Severity

    diags: list[Any] = []

    def visit(node: Any) -> None:
        nt = getattr(node, "type", None)
        if nt not in ("while_statement", "for_statement", "for_each_statement"):
            return
        if _loop_body_has_executable(node):
            return
        ch = getattr(node, "children", []) or []
        head = None
        for c in ch:
            if getattr(c, "type", None) == "DO_KEYWORD":
                break
            if getattr(c, "type", None) in ("WHILE_KEYWORD", "FOR_KEYWORD"):
                head = c
        if head is not None:
            line = head.start_point[0] + 1
            ch0 = head.start_point[1]
            end_line = head.end_point[0] + 1
            end_ch = head.end_point[1]
            diags.append(
                Diagnostic(
                    file=path,
                    line=line,
                    character=ch0,
                    end_line=end_line,
                    end_character=end_ch,
                    severity=Severity.WARNING,
                    code="BSL070",
                    message=(
                        "Loop body contains no executable statements. "
                        "Add a comment explaining intent or remove the loop."
                    ),
                )
            )

    ts_walk_preorder(root, visit)
    return diags


def diagnostics_bsl061_from_tree(path: str, root: Any) -> list[Any]:
    """BSL061 — ``Прервать``/``Break`` as last statement in loop body."""
    from onec_hbk_bsl.analysis.diagnostics import Diagnostic, Severity

    diags: list[Any] = []

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
        body = ch[i_do + 1 : i_end]
        stmts = [
            c
            for c in body
            if getattr(c, "type", None) not in ("line_comment", ";")
        ]
        if not stmts:
            return
        last = stmts[-1]
        if getattr(last, "type", None) != "break_statement":
            return
        diags.append(
            Diagnostic(
                file=path,
                line=last.start_point[0] + 1,
                character=last.start_point[1],
                end_line=last.end_point[0] + 1,
                end_character=last.end_point[1],
                severity=Severity.INFORMATION,
                code="BSL061",
                message=(
                    "Прервать/Break is the last statement of the loop body — "
                    "consider using a proper loop condition instead."
                ),
            )
        )

    ts_walk_preorder(root, visit)
    return diags


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
