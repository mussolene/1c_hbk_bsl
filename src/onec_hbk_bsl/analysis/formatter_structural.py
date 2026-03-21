"""Structural (block) indentation from tree-sitter BSL AST.

Used by :mod:`onec_hbk_bsl.analysis.formatter` together with a heuristic fallback
when the parse tree is a regex stub, contains ERROR nodes, or for preprocessor /
comment lines where layout follows sequential context.
"""
from __future__ import annotations

from typing import Any


def tree_has_errors(node: Any) -> bool:
    if node.type in ("ERROR", "error") or getattr(node, "is_missing", False):
        return True
    for c in node.children:
        if tree_has_errors(c):
            return True
    return False


def _mark_line_max(out: list[int], line: int, depth: int) -> None:
    if 0 <= line < len(out):
        out[line] = max(out[line], depth)


def _mark_statement_node(out: list[int], node: Any, depth: int) -> None:
    sl, el = node.start_point[0], node.end_point[0]
    for L in range(sl, el + 1):
        _mark_line_max(out, L, depth)


def _visit_stmt(out: list[int], node: Any, depth: int) -> None:
    t = node.type
    if t in ("procedure_definition", "function_definition"):
        _visit_proc_func(out, node, depth)
    elif t == "if_statement":
        _visit_if_statement(out, node, depth)
    elif t == "elseif_clause":
        _visit_elseif_clause(out, node, depth)
    elif t == "else_clause":
        _visit_else_clause(out, node, depth)
    elif t == "while_statement":
        _visit_while_statement(out, node, depth)
    elif t == "try_statement":
        _visit_try_statement(out, node, depth)
    elif t == "for_statement":
        _visit_for_statement(out, node, depth)
    else:
        _mark_statement_node(out, node, depth)


def _visit_proc_func(out: list[int], node: Any, depth: int) -> None:
    for c in node.children:
        ct = c.type
        if ct in ("PROCEDURE_KEYWORD", "FUNCTION_KEYWORD"):
            _mark_line_max(out, c.start_point[0], depth)
        elif ct in ("identifier", "parameters"):
            continue
        elif ct in ("ENDPROCEDURE_KEYWORD", "ENDFUNCTION_KEYWORD"):
            _mark_line_max(out, c.start_point[0], depth)
        else:
            _visit_stmt(out, c, depth + 1)


def _visit_if_statement(out: list[int], node: Any, depth: int) -> None:
    for c in node.children:
        ct = c.type
        if ct == "IF_KEYWORD":
            _mark_line_max(out, c.start_point[0], depth)
        elif ct == "THEN_KEYWORD":
            _mark_line_max(out, c.start_point[0], depth)
        elif ct == "expression":
            continue
        elif ct == "assignment_statement":
            _mark_statement_node(out, c, depth + 1)
        elif ct == "elseif_clause":
            _visit_elseif_clause(out, c, depth)
        elif ct == "else_clause":
            _visit_else_clause(out, c, depth)
        elif ct == "ENDIF_KEYWORD":
            _mark_line_max(out, c.start_point[0], depth)
        elif ct == ";":
            continue
        else:
            _visit_stmt(out, c, depth + 1)


def _visit_elseif_clause(out: list[int], node: Any, depth: int) -> None:
    for c in node.children:
        ct = c.type
        if ct == "ELSIF_KEYWORD":
            _mark_line_max(out, c.start_point[0], depth)
        elif ct == "THEN_KEYWORD":
            _mark_line_max(out, c.start_point[0], depth)
        elif ct == "expression":
            continue
        elif ct == "assignment_statement":
            _mark_statement_node(out, c, depth + 1)
        else:
            _visit_stmt(out, c, depth + 1)


def _visit_else_clause(out: list[int], node: Any, depth: int) -> None:
    for c in node.children:
        ct = c.type
        if ct == "ELSE_KEYWORD":
            _mark_line_max(out, c.start_point[0], depth)
        elif ct == "assignment_statement":
            _mark_statement_node(out, c, depth + 1)
        else:
            _visit_stmt(out, c, depth + 1)


def _visit_while_statement(out: list[int], node: Any, depth: int) -> None:
    for c in node.children:
        ct = c.type
        if ct == "WHILE_KEYWORD":
            _mark_line_max(out, c.start_point[0], depth)
        elif ct == "DO_KEYWORD":
            _mark_line_max(out, c.start_point[0], depth)
        elif ct == "ENDDO_KEYWORD":
            _mark_line_max(out, c.start_point[0], depth)
        elif ct == "expression":
            continue
        else:
            _visit_stmt(out, c, depth + 1)


def _visit_try_statement(out: list[int], node: Any, depth: int) -> None:
    for c in node.children:
        ct = c.type
        if ct == "TRY_KEYWORD":
            _mark_line_max(out, c.start_point[0], depth)
        elif ct == "EXCEPT_KEYWORD":
            _mark_line_max(out, c.start_point[0], depth)
        elif ct == "ENDTRY_KEYWORD":
            _mark_line_max(out, c.start_point[0], depth)
        elif ct == "assignment_statement":
            _mark_statement_node(out, c, depth + 1)
        elif ct == ";":
            continue
        else:
            _visit_stmt(out, c, depth + 1)


def _visit_for_statement(out: list[int], node: Any, depth: int) -> None:
    for c in node.children:
        ct = c.type
        if ct in (
            "FOR_KEYWORD",
            "TO_KEYWORD",
            "EACH_KEYWORD",
            "IN_KEYWORD",
            "DO_KEYWORD",
            "ENDDO_KEYWORD",
        ):
            _mark_line_max(out, c.start_point[0], depth)
        elif ct == "expression":
            continue
        else:
            _visit_stmt(out, c, depth + 1)


def _visit_source_file(out: list[int], node: Any, depth: int) -> None:
    for c in node.children:
        if c.type in ("procedure_definition", "function_definition"):
            _visit_proc_func(out, c, depth)
        elif c.type == "preprocessor":
            continue
        else:
            _visit_stmt(out, c, depth)


def ast_structural_indent_levels(root: Any, num_lines: int) -> list[int]:
    """Max structural indent per line (0-based) from AST only."""
    out = [0] * num_lines
    if root.type == "source_file":
        _visit_source_file(out, root, 0)
    else:
        _visit_stmt(out, root, 0)
    return out


__all__ = ["ast_structural_indent_levels", "tree_has_errors"]
