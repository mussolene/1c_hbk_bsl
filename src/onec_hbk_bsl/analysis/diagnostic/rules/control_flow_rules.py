"""
Control-flow rules that need dedicated CFG/tree helpers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from onec_hbk_bsl.analysis.lsp_positions import utf8_byte_offset_to_lsp_character


@dataclass(frozen=True)
class _Span:
    line0: int
    col0: int
    line1: int
    col1: int


def _node_span(node: Any) -> _Span | None:
    if node is None:
        return None
    sp = getattr(node, "start_point", None)
    ep = getattr(node, "end_point", None)
    if sp is None or ep is None:
        return None
    return _Span(int(sp[0]), int(sp[1]), int(ep[0]), int(ep[1]))


def _identifier_span(fn_def: Any) -> _Span | None:
    for ch in getattr(fn_def, "children", []) or []:
        if getattr(ch, "type", None) == "identifier":
            return _node_span(ch)
    return None


def _function_body_children(fn_def: Any) -> list[Any]:
    kids = list(getattr(fn_def, "children", []) or [])
    out: list[Any] = []
    for ch in kids:
        t = getattr(ch, "type", None)
        if t in ("FUNCTION_KEYWORD", "ENDFUNCTION_KEYWORD", "identifier", "parameters"):
            continue
        out.append(ch)
    return out


def _collect_if_branches(if_node: Any) -> tuple[list[list[Any]], bool]:
    ch = list(getattr(if_node, "children", []) or [])
    branches: list[list[Any]] = []
    has_else = False
    i = 0
    n = len(ch)
    while i < n:
        t = getattr(ch[i], "type", None)
        if t in ("IF_KEYWORD", "ELSIF_KEYWORD"):
            i += 1
            while i < n and getattr(ch[i], "type", None) != "THEN_KEYWORD":
                i += 1
            if i >= n:
                break
            i += 1
            start = i
            while i < n and getattr(ch[i], "type", None) not in (
                "elseif_clause",
                "else_clause",
                "ENDIF_KEYWORD",
            ):
                i += 1
            branches.append([ch[k] for k in range(start, i) if getattr(ch[k], "type", None) != ";"])
            continue
        if t == "elseif_clause":
            ec = ch[i]
            inner = list(getattr(ec, "children", []) or [])
            j = 0
            while j < len(inner) and getattr(inner[j], "type", None) != "THEN_KEYWORD":
                j += 1
            j += 1
            start = j
            while j < len(inner) and getattr(inner[j], "type", None) != "ENDIF_KEYWORD":
                j += 1
            branches.append(
                [inner[k] for k in range(start, j) if getattr(inner[k], "type", None) != ";"]
            )
            i += 1
            continue
        if t == "else_clause":
            has_else = True
            ec = ch[i]
            inner = list(getattr(ec, "children", []) or [])
            j = 0
            while j < len(inner) and getattr(inner[j], "type", None) != "ELSE_KEYWORD":
                j += 1
            j += 1
            branches.append([c for c in inner[j:] if getattr(c, "type", None) != ";"])
            i += 1
            continue
        i += 1
    return branches, has_else


def _is_meaningful_stmt(node: Any) -> bool:
    return getattr(node, "type", None) not in (None, ";", "line_comment")


def _collect_preprocessor_branches(preprocessor_node: Any) -> tuple[list[list[Any]], bool]:
    branches: list[list[Any]] = []
    current: list[Any] = []
    has_else = False
    for child in getattr(preprocessor_node, "children", []) or []:
        child_type = getattr(child, "type", None)
        if child_type in {"PREPROC_IF_KEYWORD", "PREPROC_ENDIF_KEYWORD"}:
            continue
        if child_type in {"expression", "THEN_KEYWORD"}:
            continue
        if child_type in {"PREPROC_ELSIF_KEYWORD", "PREPROC_ELSE_KEYWORD"}:
            branches.append(current)
            current = []
            if child_type == "PREPROC_ELSE_KEYWORD":
                has_else = True
            continue
        current.append(child)
    branches.append(current)
    return branches, has_else


def _preprocessor_always_returns(
    preprocessor_node: Any, *, loops_executed_at_least_once: bool = True
) -> bool:
    branches, has_else = _collect_preprocessor_branches(preprocessor_node)
    if not branches or not has_else:
        return False
    return all(
        _stmt_list_always_returns(
            branch,
            loops_executed_at_least_once=loops_executed_at_least_once,
        )
        for branch in branches
    )


def _stmt_list_always_returns(
    stmts: list[Any], *, loops_executed_at_least_once: bool = True
) -> bool:
    if not stmts:
        return False
    meaningful = [st for st in stmts if _is_meaningful_stmt(st)]
    for st in meaningful:
        t = getattr(st, "type", None)
        if t in ("return_statement", "rise_error_statement"):
            return True
        if t == "preprocessor":
            if _preprocessor_always_returns(
                st, loops_executed_at_least_once=loops_executed_at_least_once
            ):
                return True
            continue
        if t == "if_statement":
            if _if_always_returns(st, loops_executed_at_least_once=loops_executed_at_least_once):
                return True
            continue
        if t in ("while_statement", "for_statement", "for_each_statement"):
            if t == "while_statement" and _while_literal_true(st):
                return True
            if loops_executed_at_least_once and _loop_body_always_returns(
                st, loops_executed_at_least_once=loops_executed_at_least_once
            ):
                return True
            if _loop_body_always_returns(
                st, loops_executed_at_least_once=loops_executed_at_least_once
            ):
                return True
            continue
        if t == "try_statement":
            if _try_always_returns(st, loops_executed_at_least_once=loops_executed_at_least_once):
                return True
            continue
    return False


def _loop_body_stmts(loop_node: Any) -> list[Any]:
    out: list[Any] = []
    for ch in getattr(loop_node, "children", []) or []:
        t = getattr(ch, "type", None)
        if t in (
            "WHILE_KEYWORD",
            "FOR_KEYWORD",
            "FOREACH_KEYWORD",
            "DO_KEYWORD",
            "ENDDO_KEYWORD",
            "TO_KEYWORD",
            "IN_KEYWORD",
            "expression",
            ";",
        ):
            continue
        out.append(ch)
    return out


def _loop_body_always_returns(loop_node: Any, *, loops_executed_at_least_once: bool = True) -> bool:
    return _stmt_list_always_returns(
        _loop_body_stmts(loop_node),
        loops_executed_at_least_once=loops_executed_at_least_once,
    )


def _try_always_returns(try_node: Any, *, loops_executed_at_least_once: bool = True) -> bool:
    parts: list[list[Any]] = [[], []]
    current_part = 0
    for ch in getattr(try_node, "children", []) or []:
        t = getattr(ch, "type", None)
        if t == "TRY_KEYWORD":
            continue
        if t == "EXCEPT_KEYWORD":
            current_part = 1
            continue
        if t in ("ENDTRY_KEYWORD", ";"):
            continue
        parts[current_part].append(ch)
    if not parts[0] or not parts[1]:
        return False
    return all(
        _stmt_list_always_returns(
            b,
            loops_executed_at_least_once=loops_executed_at_least_once,
        )
        for b in parts
    )


def _if_always_returns(if_node: Any, *, loops_executed_at_least_once: bool = True) -> bool:
    branches, has_else = _collect_if_branches(if_node)
    if not branches or not has_else:
        return False
    return all(
        _stmt_list_always_returns(
            b,
            loops_executed_at_least_once=loops_executed_at_least_once,
        )
        for b in branches
    )


def _if_has_elseif(if_node: Any) -> bool:
    return any(
        getattr(child, "type", None) == "elseif_clause"
        for child in getattr(if_node, "children", []) or []
    )


def _if_has_else(if_node: Any) -> bool:
    return any(
        getattr(child, "type", None) == "else_clause"
        for child in getattr(if_node, "children", []) or []
    )


def _if_may_exit_to_successor_without_return(
    if_node: Any, *, loops_executed_at_least_once: bool = True
) -> bool:
    branches, has_else = _collect_if_branches(if_node)
    if not branches or not has_else:
        return True
    return any(
        not _stmt_list_always_returns(
            b,
            loops_executed_at_least_once=loops_executed_at_least_once,
        )
        for b in branches
    )


def _while_literal_true(while_node: Any) -> bool:
    for ch in getattr(while_node, "children", []) or []:
        if getattr(ch, "type", None) != "expression":
            continue
        for g in getattr(ch, "children", []) or []:
            if getattr(g, "type", None) == "const_expression":
                for h in getattr(g, "children", []) or []:
                    if getattr(h, "type", None) == "boolean":
                        for t in getattr(h, "children", []) or []:
                            if getattr(t, "type", None) == "TRUE_KEYWORD":
                                return True
    return False


def implicit_exit_reachable(
    stmts: list[Any],
    *,
    loops_executed_at_least_once: bool,
    at_top_level: bool,
) -> bool:
    i = 0
    while i < len(stmts):
        s = stmts[i]
        t = getattr(s, "type", None)
        if t in ("return_statement", "rise_error_statement"):
            return False
        if t == "preprocessor":
            if _preprocessor_always_returns(
                s, loops_executed_at_least_once=loops_executed_at_least_once
            ):
                return False
            i += 1
            continue
        if t == "if_statement":
            if (
                at_top_level
                and i + 1 >= len(stmts)
                and _if_may_exit_to_successor_without_return(
                    s,
                    loops_executed_at_least_once=loops_executed_at_least_once,
                )
                and not _if_has_elseif(s)
                and not _if_has_else(s)
            ):
                return False
            if _if_may_exit_to_successor_without_return(
                s,
                loops_executed_at_least_once=loops_executed_at_least_once,
            ):
                i += 1
                continue
            return False
        if t in ("while_statement", "for_statement", "for_each_statement"):
            if t == "while_statement" and _while_literal_true(s):
                return False
            body_always_returns = _loop_body_always_returns(
                s,
                loops_executed_at_least_once=loops_executed_at_least_once,
            )
            if loops_executed_at_least_once and body_always_returns:
                return False
            if loops_executed_at_least_once and at_top_level:
                i += 1
                continue
            if not body_always_returns:
                i += 1
                continue
            i += 1
            continue
        if t == "try_statement":
            if not _try_always_returns(
                s,
                loops_executed_at_least_once=loops_executed_at_least_once,
            ):
                i += 1
                continue
            return False
        i += 1
    return True


def _fn_subtree_has_parse_error(fn_def: Any) -> bool:
    def walk(node: Any) -> bool:
        if getattr(node, "type", None) == "ERROR":
            return True
        if bool(getattr(node, "is_missing", False)):
            return True
        return any(walk(child) for child in getattr(node, "children", []) or [])

    return walk(fn_def)


def _fn_has_return(fn_def: Any) -> bool:
    found = False

    def walk(node: Any) -> None:
        nonlocal found
        node_type = getattr(node, "type", None)
        if node_type in {"function_definition", "procedure_definition"}:
            # Nested routines do not contribute to outer function return paths.
            return
        if node_type == "return_statement":
            found = True
            return
        for child in getattr(node, "children", []) or []:
            walk(child)

    for child in _function_body_children(fn_def):
        walk(child)
    return found


def bsl148_function_name_spans(
    tree_or_root: Any,
    *,
    loops_executed_at_least_once: bool = True,
) -> list[tuple[int, int, int]]:
    root = getattr(tree_or_root, "root_node", None)
    if root is None:
        root = tree_or_root

    out: list[tuple[int, int, int]] = []

    def scan(node: Any) -> None:
        if getattr(node, "type", None) == "function_definition":
            if not _fn_subtree_has_parse_error(node) and _fn_has_return(node):
                body = _function_body_children(node)
                if implicit_exit_reachable(
                    body,
                    loops_executed_at_least_once=loops_executed_at_least_once,
                    at_top_level=True,
                ):
                    ident = _identifier_span(node)
                    if ident is not None:
                        # Tree root text can be degraded for very large files in some
                        # parser states; use function-local header text for stable
                        # byte->LSP conversion of identifier anchor.
                        raw_fn_text = getattr(node, "text", b"")
                        if isinstance(raw_fn_text, bytes):
                            fn_header = raw_fn_text.decode("utf-8", errors="replace").splitlines()
                            line_text = fn_header[0] if fn_header else ""
                        else:
                            fn_header = str(raw_fn_text or "").splitlines()
                            line_text = fn_header[0] if fn_header else ""
                        out.append(
                            (
                                ident.line0 + 1,
                                utf8_byte_offset_to_lsp_character(line_text, ident.col0),
                                utf8_byte_offset_to_lsp_character(line_text, ident.col1),
                            )
                        )
        for child in getattr(node, "children", []) or []:
            scan(child)

    scan(root)
    return out
