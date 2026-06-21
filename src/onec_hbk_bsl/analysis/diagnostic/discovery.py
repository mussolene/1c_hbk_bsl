from __future__ import annotations

from typing import Any


def find_procedures_from_tree(tree: Any) -> list[Any]:
    from onec_hbk_bsl.analysis import diagnostics as _diag

    root = getattr(tree, "root_node", None)
    if root is None or not isinstance(getattr(root, "text", None), (bytes, type(None))):
        return []
    result: list[Any] = []

    def collect(node: Any) -> None:
        if node.type in ("procedure_definition", "function_definition"):
            proc = _diag._ts_node_to_proc_info(node)
            if proc:
                result.append(proc)
            return
        for child in node.children:
            collect(child)

    collect(root)
    return result


def find_regions(content: str) -> list[Any]:
    from onec_hbk_bsl.analysis import diagnostics as _diag

    opens: list[tuple[int, str]] = []
    closes: list[int] = []

    for m in _diag._RE_REGION_OPEN.finditer(content):
        line_idx = content[: m.start()].count("\n")
        opens.append((line_idx, m.group("name")))
    for m in _diag._RE_REGION_CLOSE.finditer(content):
        line_idx = content[: m.start()].count("\n")
        closes.append(line_idx)

    closes_sorted = sorted(closes)
    used_closes: set[int] = set()
    result: list[Any] = []
    for start_idx, name in sorted(opens, key=lambda x: x[0]):
        end_idx = start_idx + 1
        for c in closes_sorted:
            if c > start_idx and c not in used_closes:
                end_idx = c
                used_closes.add(c)
                break
        result.append(_diag._RegionInfo(name=name, start_idx=start_idx, end_idx=end_idx))
    return result


def find_regions_from_tree(tree: Any) -> list[Any]:
    from onec_hbk_bsl.analysis import diagnostics as _diag

    root = getattr(tree, "root_node", None)
    if root is None or not isinstance(getattr(root, "text", None), bytes):
        return []

    opens: list[tuple[int, str]] = []
    closes: list[int] = []
    result: list[Any] = []

    def visit(node: Any) -> None:
        if getattr(node, "type", None) == "preprocessor":
            child_types = {getattr(c, "type", None) for c in getattr(node, "children", [])}
            start_idx = node.start_point[0] if getattr(node, "start_point", None) else 0
            if "PREPROC_REGION_KEYWORD" in child_types:
                region_name = ""
                seen_keyword = False
                for c in getattr(node, "children", []):
                    if getattr(c, "type", None) == "PREPROC_REGION_KEYWORD":
                        seen_keyword = True
                        continue
                    if seen_keyword and getattr(c, "type", None) == "identifier":
                        region_name = _diag._ts_node_text(c)
                        break
                if "PREPROC_ENDREGION_KEYWORD" in child_types:
                    end_idx = (
                        node.end_point[0] if getattr(node, "end_point", None) else start_idx + 1
                    )
                    result.append(
                        _diag._RegionInfo(name=region_name, start_idx=start_idx, end_idx=end_idx)
                    )
                    for child in getattr(node, "children", []):
                        visit(child)
                    return
                opens.append((start_idx, region_name))
                return
            if "PREPROC_ENDREGION_KEYWORD" in child_types:
                closes.append(node.start_point[0])
                return
        for child in getattr(node, "children", []):
            visit(child)

    visit(root)

    closes_sorted = sorted(closes)
    used_closes: set[int] = set()
    for start_idx, name in sorted(opens, key=lambda x: x[0]):
        end_idx = start_idx + 1
        for c in closes_sorted:
            if c > start_idx and c not in used_closes:
                end_idx = c
                used_closes.add(c)
                break
        result.append(_diag._RegionInfo(name=name, start_idx=start_idx, end_idx=end_idx))
    return result


def find_proc_definition_node(tree: Any, proc: Any) -> Any | None:
    from onec_hbk_bsl.analysis import diagnostics as _diag

    root = getattr(tree, "root_node", None)
    if root is None or not isinstance(getattr(root, "text", None), (bytes, bytearray)):
        return None

    def walk(node: Any) -> Any | None:
        if node.type in ("procedure_definition", "function_definition"):
            info = _diag._ts_node_to_proc_info(node)
            if (
                info
                and info.name == proc.name
                and info.start_idx == proc.start_idx
                and info.kind == proc.kind
            ):
                return node
        for child in node.children:
            found = walk(child)
            if found is not None:
                return found
        return None

    return walk(root)


def build_proc_node_map(tree: Any) -> dict[tuple[str, int, str], Any]:
    from onec_hbk_bsl.analysis import diagnostics as _diag

    out: dict[tuple[str, int, str], Any] = {}
    root = getattr(tree, "root_node", None)
    if root is None or not isinstance(getattr(root, "text", None), (bytes, bytearray)):
        return out

    def collect(node: Any) -> None:
        if node.type in ("procedure_definition", "function_definition"):
            info = _diag._ts_node_to_proc_info(node)
            if info:
                out[(info.name, info.start_idx, info.kind)] = node
            return
        for child in node.children:
            collect(child)

    collect(root)
    return out


def ts_first_body_statement_line_idx(proc_node: Any) -> int | None:
    for ch in proc_node.children:
        if ch.type == "parameters":
            continue
        if ch.type == "EXPORT_KEYWORD":
            continue
        if ch.type in ("ENDPROCEDURE_KEYWORD", "ENDFUNCTION_KEYWORD"):
            return None
        return ch.start_point[0]
    return None


def proc_body_start_line_idx_fallback(lines: list[str], proc: Any) -> int:
    i = proc.start_idx
    depth = 0
    started = False
    while i < len(lines) and i <= proc.end_idx:
        for ch in lines[i]:
            if ch == "(":
                depth += 1
                started = True
            elif ch == ")":
                depth -= 1
        if started and depth == 0:
            return i + 1
        i += 1
    return proc.start_idx + 1


def export_description_anchor_line_idx(lines: list[str], header_idx: int) -> int | None:
    from onec_hbk_bsl.analysis import diagnostics as _diag

    j = header_idx - 1
    while j >= 0:
        raw = lines[j]
        if not raw.strip():
            j -= 1
            continue
        if _diag._RE_FORM_COMPILER_DIRECTIVE_LINE.match(raw):
            j -= 1
            continue
        return j
    return None


def collect_identifier_casefolds_in_proc_body(proc_node: Any) -> set[str]:
    from onec_hbk_bsl.analysis import diagnostics as _diag

    out: set[str] = set()

    def walk(n: Any) -> None:
        if n.type == "parameters":
            return
        if n.type == "identifier":
            t = _diag._ts_node_text(n)
            if t:
                out.add(t.casefold())
        for c in n.children:
            walk(c)

    for child in proc_node.children:
        if child.type == "parameters":
            continue
        walk(child)
    return out
