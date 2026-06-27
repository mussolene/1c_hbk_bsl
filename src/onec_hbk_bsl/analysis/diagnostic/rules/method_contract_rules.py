from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from onec_hbk_bsl.analysis.diagnostic.domain.method_doc_comment import (
    build_method_doc_comment,
)

if TYPE_CHECKING:
    from onec_hbk_bsl.analysis.diagnostic.models import ProcInfo as _ProcInfo


def _diag_module() -> Any:
    from onec_hbk_bsl.analysis import diagnostics as _diag

    return _diag


def run_bsl192_193_194_228_266_method_contract_diagnostics(
    path: str,
    lines: list[str],
    procs: list[_ProcInfo],
    codes: tuple[str, ...],
    rule_enabled: Any,
) -> list[Any]:
    _diag = _diag_module()
    enabled = {code for code in codes if rule_enabled(code)}
    if not enabled:
        return []

    diags: list[Any] = []
    for proc in procs:
        start_char, end_char = _diag._proc_name_span(lines, proc)

        if (
            "BSL192" in enabled
            and proc.kind == "function"
            and _diag._RE_BSL192_GET.match(proc.name)
        ):
            diags.append(
                _diag.Diagnostic(
                    file=path,
                    line=proc.start_idx + 1,
                    character=start_char,
                    end_line=proc.start_idx + 1,
                    end_character=end_char,
                    severity=_diag.Severity.INFORMATION,
                    code="BSL192",
                )
            )

        def param_list_span(
            current_proc: _ProcInfo,
            proc_start_idx: int,
            fallback_start: int,
            fallback_end: int,
        ) -> tuple[int, int, int, int]:
            params_start_idx = getattr(current_proc, "params_start_idx", None)
            params_start_character = getattr(current_proc, "params_start_character", None)
            params_end_idx = getattr(current_proc, "params_end_idx", None)
            params_end_character = getattr(current_proc, "params_end_character", None)
            if (
                params_start_idx is not None
                and params_start_character is not None
                and params_end_idx is not None
                and params_end_character is not None
            ):
                return (
                    params_start_idx + 1,
                    params_start_character,
                    params_end_idx + 1,
                    params_end_character,
                )
            header_line = lines[proc_start_idx] if 0 <= proc_start_idx < len(lines) else ""
            open_paren = header_line.find("(")
            close_paren = header_line.rfind(")")
            if open_paren >= 0 and close_paren > open_paren:
                return proc_start_idx + 1, open_paren + 1, proc_start_idx + 1, close_paren
            return proc_start_idx + 1, fallback_start, proc_start_idx + 1, fallback_end

        if "BSL228" in enabled and proc.optional_params:
            seen_optional = False
            for param in proc.params:
                if param in proc.optional_params:
                    seen_optional = True
                    continue
                if seen_optional:
                    start_line, param_start, end_line, param_end = param_list_span(
                        proc, proc.start_idx, start_char, end_char
                    )
                    diags.append(
                        _diag.Diagnostic(
                            file=path,
                            line=start_line,
                            character=param_start,
                            end_line=end_line,
                            end_character=param_end,
                            severity=_diag.Severity.WARNING,
                            code="BSL228",
                        )
                    )
                    break

        if "BSL193" in enabled and proc.kind == "function":
            ref_params = {
                p.casefold()
                for p in proc.params
                if p.casefold() not in {n.casefold() for n in proc.val_params}
            }
            seen_out: set[str] = set()
            body_start_idx = _diag._proc_body_start_line_idx_fallback(lines, proc)
            for idx in range(body_start_idx, proc.end_idx + 1):
                code_line = lines[idx].split("//", 1)[0]
                m_assign = _diag._RE_ASSIGN_LHS.match(code_line)
                if not m_assign:
                    continue
                lhs_cf = m_assign.group("name").casefold()
                if lhs_cf in ref_params and lhs_cf not in seen_out:
                    seen_out.add(lhs_cf)
                    diags.append(
                        _diag.Diagnostic(
                            file=path,
                            line=idx + 1,
                            character=m_assign.start("name"),
                            end_line=idx + 1,
                            end_character=m_assign.end("name"),
                            severity=_diag.Severity.WARNING,
                            code="BSL193",
                        )
                    )

        if (
            "BSL194" in enabled
            and proc.kind == "function"
            and not proc.name.casefold().startswith(("подключаемый_", "attachable_"))
        ):
            return_exprs: list[str] = []
            for idx in range(proc.start_idx + 1, proc.end_idx + 1):
                code_line = lines[idx].split("//", 1)[0]
                m_return = _diag._RE_RETURN_SIMPLE_EXPR.match(code_line)
                if not m_return:
                    continue
                expr = m_return.group(1).strip()
                if not (
                    re.fullmatch(r"-?\d+(?:\.\d+)?", expr)
                    or re.fullmatch(r'"(?:[^"]|"")*"', expr)
                    or expr.casefold()
                    in {"истина", "ложь", "true", "false", "неопределено", "undefined", "null"}
                ):
                    return_exprs = []
                    break
                return_exprs.append(expr.casefold())
            if len(return_exprs) > 1 and len(set(return_exprs)) == 1:
                diags.append(
                    _diag.Diagnostic(
                        file=path,
                        line=proc.start_idx + 1,
                        character=start_char,
                        end_line=proc.start_idx + 1,
                        end_character=end_char,
                        severity=_diag.Severity.ERROR,
                        code="BSL194",
                    )
                )

        if "BSL266" in enabled:
            cancel_params = {p.casefold() for p in proc.params if _diag._RE_BSL266_CANCEL.match(p)}
            if cancel_params:
                for idx in range(proc.start_idx + 1, proc.end_idx + 1):
                    code_line = lines[idx].split("//", 1)[0].strip()
                    m_assign = _diag._RE_ASSIGN_LHS.match(code_line)
                    if not m_assign:
                        continue
                    lhs = m_assign.group("name")
                    lhs_cf = lhs.casefold()
                    if lhs_cf not in cancel_params:
                        continue
                    rhs = code_line[m_assign.end() :].rstrip().rstrip(";").strip()
                    rhs_cf = rhs.casefold()
                    valid = rhs_cf in {"истина", "true"} or (
                        re.search(r"\b(?:или|or)\b", rhs, re.IGNORECASE)
                        and re.search(rf"\b{re.escape(lhs)}\b", rhs, re.IGNORECASE)
                    )
                    if not valid:
                        diags.append(
                            _diag.Diagnostic(
                                file=path,
                                line=idx + 1,
                                character=m_assign.start("name"),
                                end_line=idx + 1,
                                end_character=len(lines[idx].rstrip()),
                                severity=_diag.Severity.WARNING,
                                code="BSL266",
                            )
                        )

    return diags


def run_bsl212_missed_required_parameter(
    path: str,
    content: str,
    lines: list[str],
    procs: list[_ProcInfo],
    calls: list[Any],
) -> list[Any]:
    _diag = _diag_module()
    proc_by_name = {proc.name.casefold(): proc for proc in procs}
    if not proc_by_name or not calls:
        return []
    required_params_by_name = {
        name: tuple(param for param in proc.params if param not in proc.optional_params)
        for name, proc in proc_by_name.items()
    }

    diags: list[Any] = []
    line_starts = _diag.line_start_offsets(content)
    for call in calls:
        callee_name = call.callee_name.casefold()
        callee = proc_by_name.get(callee_name)
        if callee is None:
            continue
        line_text = lines[call.caller_line - 1] if 0 <= call.caller_line - 1 < len(lines) else ""
        before_call = line_text[: call.caller_character].rstrip()
        if before_call.endswith("."):
            continue
        required_params = required_params_by_name.get(callee_name, ())
        if not required_params:
            continue
        arg_presence = _diag._extract_call_argument_presence(
            content,
            line_starts,
            line=call.caller_line,
            character=call.caller_character,
            callee_name=call.callee_name,
        )
        if arg_presence is None:
            continue

        missed: list[str] = []
        for idx, param_name in enumerate(callee.params):
            if param_name in callee.optional_params:
                continue
            if idx >= len(arg_presence) or not arg_presence[idx]:
                missed.append(param_name)

        if not missed:
            continue
        start = line_starts[call.caller_line - 1] + call.caller_character
        match = re.match(rf"{re.escape(call.callee_name)}\s*\(", content[start:], re.IGNORECASE)
        end_character = len(line_text.rstrip())
        if match:
            open_idx = start + match.end() - 1
            close_idx = _diag._find_matching_paren(content, open_idx)
            if close_idx >= 0:
                end_character = close_idx - line_starts[call.caller_line - 1] + 1
        diags.append(
            _diag.Diagnostic(
                file=path,
                line=call.caller_line,
                character=call.caller_character,
                end_line=call.caller_line,
                end_character=end_character,
                severity=_diag.Severity.ERROR,
                code="BSL212",
            )
        )
    return diags


def run_bsl215_missing_parameter_description(
    path: str,
    lines: list[str],
    procs: list[_ProcInfo],
    line_comment_nodes: list[Any] | None = None,
) -> list[Any]:
    _diag = _diag_module()
    diags: list[Any] = []
    legacy_doc_path = bool(re.search(r"(?:ManagerModule|ObjectModule)\.bsl$", path))

    for proc in procs:
        doc_comment = build_method_doc_comment(
            lines,
            proc,
            line_comment_nodes=line_comment_nodes,
            legacy_doc_path=legacy_doc_path,
        )
        if doc_comment is None or not doc_comment.has_method_documentation:
            continue

        actual_params_cf = {p.casefold() for p in proc.params}
        try:
            header_col = lines[proc.start_idx].index(proc.name)
        except ValueError:
            header_col = 0

        if not doc_comment.has_params_section:
            if not proc.params:
                continue
            diags.append(
                _diag.Diagnostic(
                    file=path,
                    line=proc.start_idx + 1,
                    character=header_col,
                    end_line=proc.start_idx + 1,
                    end_character=header_col + len(proc.name),
                    severity=_diag.Severity.WARNING,
                    code="BSL215",
                )
            )
            continue

        documented_entries = list(doc_comment.documented_names)
        empty_description_entries = set(doc_comment.empty_description_names)
        stale_reference_entries = list(doc_comment.stale_reference_entries)

        documented_cf = {p.casefold(): p for p in documented_entries}
        for actual_param in proc.params:
            if actual_param.casefold() in documented_cf:
                continue
            if legacy_doc_path and any(
                re.search(r"^\s*// [ \t]*" + re.escape(actual_param) + r"\s*-", cl, re.IGNORECASE)
                and not re.search(r"\s-\s*(?:см\.|see)\s+\S+[.;]\s*$", cl, re.IGNORECASE)
                for cl in doc_comment.lines[(doc_comment.params_section_offset or 0) + 1 :]
            ):
                documented_entries.append(actual_param)
                documented_cf[actual_param.casefold()] = actual_param

        param_lines: dict[str, int] = {}
        scan_idx = proc.start_idx
        paren_depth = 0
        header_done = False
        while scan_idx < len(lines) and not header_done:
            sl = lines[scan_idx]
            for ch in sl:
                if ch == "(":
                    paren_depth += 1
                elif ch == ")":
                    paren_depth -= 1
                    if paren_depth == 0:
                        header_done = True
                        break
            for pname in proc.params:
                pcf = pname.casefold()
                if pcf not in param_lines and re.search(
                    r"\b" + re.escape(pname) + r"\b", sl, re.IGNORECASE
                ):
                    param_lines[pcf] = scan_idx
            scan_idx += 1

        missing_params = [pname for pname in proc.params if pname.casefold() not in documented_cf]
        if (
            not missing_params
            and len(proc.params) == 1
            and len(documented_entries) == 1
            and doc_comment.documented_entries
            and " - " not in doc_comment.documented_entries[0].tail
            and "," not in doc_comment.documented_entries[0].tail
            and not re.match(
                r"^\s*(?:см\.|see)\s+",
                doc_comment.documented_entries[0].tail,
                re.IGNORECASE,
            )
            and not doc_comment.documented_entries[0].tail.strip().endswith(":")
            and (
                not legacy_doc_path
                or doc_comment.documented_entries[0].tail.strip().casefold()
                not in {
                    "дата",
                    "date",
                    "строка",
                    "string",
                    "число",
                    "number",
                    "булево",
                    "boolean",
                }
            )
        ):
            missing_params = list(proc.params)
            documented_cf = {}
        if doc_comment.force_all_params_missing:
            missing_params = list(proc.params)
            documented_cf = {}
        if missing_params and not documented_cf:
            diags.append(
                _diag.Diagnostic(
                    file=path,
                    line=proc.start_idx + 1,
                    character=header_col,
                    end_line=proc.start_idx + 1,
                    end_character=header_col + len(proc.name),
                    severity=_diag.Severity.WARNING,
                    code="BSL215",
                )
            )
        else:
            for pname in missing_params:
                pcf = pname.casefold()
                param_line_idx = param_lines.get(pcf, proc.start_idx)
                pl = lines[param_line_idx]
                m = re.search(r"\b" + re.escape(pname) + r"\b", pl, re.IGNORECASE)
                col = m.start() if m else header_col
                diags.append(
                    _diag.Diagnostic(
                        file=path,
                        line=param_line_idx + 1,
                        character=col,
                        end_line=param_line_idx + 1,
                        end_character=col + len(pname),
                        severity=_diag.Severity.WARNING,
                        code="BSL215",
                    )
                )

        for pname in proc.params:
            pcf = pname.casefold()
            if pcf not in empty_description_entries:
                continue
            param_line_idx = param_lines.get(pcf, proc.start_idx)
            pl = lines[param_line_idx]
            m = re.search(r"\b" + re.escape(pname) + r"\b", pl, re.IGNORECASE)
            col = m.start() if m else header_col
            diags.append(
                _diag.Diagnostic(
                    file=path,
                    line=param_line_idx + 1,
                    character=col,
                    end_line=param_line_idx + 1,
                    end_character=col + len(pname),
                    severity=_diag.Severity.WARNING,
                    code="BSL215",
                )
            )
        seen_actual_docs: set[str] = set()
        extra: list[str] = []
        for pname in documented_entries:
            pcf = pname.casefold()
            if pcf not in actual_params_cf or pcf in seen_actual_docs:
                extra.append(pname)
            else:
                seen_actual_docs.add(pcf)
        extra.extend(stale_reference_entries)
        if extra and actual_params_cf:
            diags.append(
                _diag.Diagnostic(
                    file=path,
                    line=proc.start_idx + 1,
                    character=header_col,
                    end_line=proc.start_idx + 1,
                    end_character=header_col + len(proc.name),
                    severity=_diag.Severity.WARNING,
                    code="BSL215",
                )
            )
        elif not missing_params and documented_entries:
            actual_order = [p.casefold() for p in proc.params]
            documented_order = [
                p.casefold() for p in documented_entries if p.casefold() in actual_params_cf
            ]
            if documented_order != actual_order:
                diags.append(
                    _diag.Diagnostic(
                        file=path,
                        line=proc.start_idx + 1,
                        character=header_col,
                        end_line=proc.start_idx + 1,
                        end_character=header_col + len(proc.name),
                        severity=_diag.Severity.WARNING,
                        code="BSL215",
                    )
                )
    return diags


_RE_BSL233_API_REGION = re.compile(
    r"^\s*#(?:Область|Region)\s+(ПрограммныйИнтерфейс|Public)\s*$",
    re.IGNORECASE,
)
_RE_BSL233_REGION_START = re.compile(r"^\s*#(?:Область|Region)\b", re.IGNORECASE)
_RE_BSL233_REGION_END = re.compile(r"^\s*#(?:КонецОбласти|EndRegion)\b", re.IGNORECASE)


def run_bsl233_public_methods_description(
    path: str,
    lines: list[str],
    procs: list[_ProcInfo],
) -> list[Any]:
    _diag = _diag_module()
    diags: list[Any] = []
    region_stack: list[str] = []
    root_region_at: dict[int, str] = {}

    for idx, line in enumerate(lines):
        if _RE_BSL233_REGION_END.match(line):
            if region_stack:
                region_stack.pop()
        elif _RE_BSL233_REGION_START.match(line):
            m = re.match(r"^\s*#(?:Область|Region)\s+(\S+)", line, re.IGNORECASE)
            region_name = m.group(1) if m else ""
            region_stack.append(region_name)
        if region_stack:
            root_region_at[idx] = region_stack[0]

    for proc in procs:
        if not proc.is_export:
            continue
        root_region = root_region_at.get(proc.start_idx, "")
        if not _RE_BSL233_API_REGION.match(f"#Область {root_region}" if root_region else ""):
            continue

        doc_comment = build_method_doc_comment(lines, proc, skip_blank_lines=True)
        has_description = (
            doc_comment is not None and doc_comment.has_method_documentation
        )

        if not has_description:
            header_line = lines[proc.start_idx]
            try:
                col = header_line.index(proc.name)
            except ValueError:
                col = 0
            diags.append(
                _diag.Diagnostic(
                    file=path,
                    line=proc.start_idx + 1,
                    character=col,
                    end_line=proc.start_idx + 1,
                    end_character=col + len(proc.name),
                    severity=_diag.Severity.INFORMATION,
                    code="BSL233",
                )
            )
    return diags


def run_bsl254_transferring_parameters(
    symbol_index: Any,
    path: str,
    lines: list[str],
    procs: list[_ProcInfo],
    tree: Any,
    proc_node_map: dict[tuple[str, int, str], Any] | None = None,
) -> list[Any]:
    _diag = _diag_module()
    if symbol_index is None or not _diag._ts_tree_ok_for_rules(tree):
        return []

    diags: list[Any] = []
    file_lines_cache: dict[str, list[str]] = {path: lines}
    proc_cache: dict[str, list[_ProcInfo]] = {path: procs}
    for proc in procs:
        pnode = _method_proc_node(_diag, tree, proc, proc_node_map)
        if pnode is None:
            continue
        if _diag._procedure_compiler_execution_context(lines, proc) != "server":
            continue
        if not proc.params:
            continue
        missing_val = [
            p
            for p in proc.params
            if p and p.casefold() not in {n.casefold() for n in proc.val_params}
        ]
        if not missing_val:
            continue
        callers = getattr(symbol_index, "find_callers", lambda *_args, **_kwargs: [])(
            proc.name,
            limit=None,
        )
        client_callers = [
            row
            for row in callers
            if _diag._caller_is_client_method(
                str(row.get("caller_file") or ""),
                row.get("caller_name"),
                int(row.get("caller_line") or 0),
                current_path=path,
                current_lines=lines,
                current_procs=procs,
                file_lines_cache=file_lines_cache,
                proc_cache=proc_cache,
            )
        ]
        if not client_callers:
            continue
        assigned = _assigned_names_from_cst(_diag, pnode)
        for param_name in missing_val:
            if param_name.casefold() in assigned:
                continue
            location = _diag._proc_param_location(lines, proc, param_name)
            if location is None:
                line_idx = proc.start_idx
                header_line = lines[proc.start_idx] if proc.start_idx < len(lines) else ""
                c0 = proc.header_col
                c1 = len(header_line.rstrip())
            else:
                line_idx, c0, c1 = location
            diags.append(
                _diag.Diagnostic(
                    file=path,
                    line=line_idx + 1,
                    character=c0,
                    end_line=line_idx + 1,
                    end_character=c1,
                    severity=_diag.Severity.WARNING,
                    code="BSL254",
                )
            )
    return diags


def run_bsl224_nested_function_in_parameters(
    path: str,
    lines: list[str],
    tree: Any,
    nodes_by_type: dict[str, list[Any]] | None = None,
) -> list[Any]:
    _diag = _diag_module()
    root = getattr(tree, "root_node", None)
    allowed_names = {"нстр", "nstr", "предопределенноезначение", "predefinedvalue"}
    diags: list[Any] = []
    seen: set[tuple[int, int]] = set()

    def call_name_and_args(node: Any) -> tuple[str, Any | None, Any | None, Any | None, Any | None]:
        if getattr(node, "type", None) == "call_expression":
            method_node = _diag._ts_child_of_type(node, "method_call")
            if method_node is not None:
                name, _, args, _, name_node = call_name_and_args(method_node)
                return name, name_node, args, method_node, name_node
            return "", None, None, None, None
        ident = _diag._ts_child_of_type(node, "identifier")
        args = _diag._ts_child_of_type(node, "arguments")
        return _diag._ts_node_text(ident), ident, args, node, ident

    def arg_expr_nodes(args: Any) -> list[Any]:
        return [
            child for child in getattr(args, "children", []) or [] if child.type == "expression"
        ]

    def contains_forbidden_nested_call(args: Any) -> bool:
        for child in _diag._ts_walk(args):
            node_type = getattr(child, "type", None)
            if node_type == "call_expression":
                return True
            if node_type == "method_call":
                name, _, _, _, _ = call_name_and_args(child)
                if name.casefold() not in allowed_names:
                    return True
            elif node_type == "new_expression":
                _, _, nested_args, _, _ = call_name_and_args(child)
                if nested_args is not None and arg_expr_nodes(nested_args):
                    return True
        return False

    if root is not None and isinstance(getattr(root, "text", None), (bytes, bytearray)):
        if nodes_by_type is None:
            candidate_nodes = _diag._ts_walk(root)
        else:
            candidate_nodes = (
                nodes_by_type.get("call_expression", [])
                + nodes_by_type.get("method_call", [])
                + nodes_by_type.get("new_expression", [])
            )

        for node in candidate_nodes:
            node_type = getattr(node, "type", None)
            if node_type not in {"call_expression", "method_call", "new_expression"}:
                continue
            if (
                node_type == "method_call"
                and getattr(getattr(node, "parent", None), "type", None) == "call_expression"
            ):
                continue
            if node.start_point[0] == node.end_point[0]:
                continue

            name, anchor, args, call_node, name_node = call_name_and_args(node)
            if anchor is None or args is None or call_node is None or name_node is None:
                continue

            exprs = arg_expr_nodes(args)
            if not exprs:
                continue
            if not any(expr.start_point[0] != expr.end_point[0] for expr in exprs):
                continue
            if not contains_forbidden_nested_call(args):
                continue

            start_line_idx = anchor.start_point[0]
            end_line_idx = name_node.end_point[0]
            start_line_text = lines[start_line_idx] if start_line_idx < len(lines) else ""
            end_line_text = lines[end_line_idx] if end_line_idx < len(lines) else ""
            exact_start = start_line_text.find(name)
            start_char = (
                exact_start
                if exact_start >= 0
                else _diag.utf8_byte_offset_to_lsp_character(start_line_text, anchor.start_point[1])
            )
            diags.append(
                _diag.Diagnostic(
                    file=path,
                    line=start_line_idx + 1,
                    character=start_char,
                    end_line=end_line_idx + 1,
                    end_character=start_char + len(name)
                    if start_line_idx == end_line_idx
                    else _diag.utf8_byte_offset_to_lsp_character(
                        end_line_text, name_node.end_point[1]
                    ),
                    severity=_diag.Severity.INFORMATION,
                    code="BSL224",
                )
            )
            seen.add((start_line_idx, start_char))

    fallback_names = {"стрзаменить", "strreplace", "вставить", "insert"}
    call_start_re = re.compile(r"(?:(?P<dot>\.)\s*)?(?P<name>[A-Za-zА-Яа-яЁё_]\w*)\s*\(")
    nested_call_re = re.compile(r"\b([A-Za-zА-Яа-яЁё_]\w*)\s*\(", re.IGNORECASE)

    def strip_strings(text: str) -> str:
        chars = list(text)
        pos = 0
        in_string = False
        while pos < len(chars):
            ch = chars[pos]
            if in_string:
                chars[pos] = " "
                if ch == '"':
                    if pos + 1 < len(chars) and chars[pos + 1] == '"':
                        chars[pos + 1] = " "
                        pos += 2
                        continue
                    in_string = False
                pos += 1
                continue
            if ch == '"':
                chars[pos] = " "
                in_string = True
            pos += 1
        return "".join(chars)

    def call_text_from(line_idx: int, open_col: int) -> str:
        depth = 0
        parts: list[str] = []
        for idx in range(line_idx, min(len(lines), line_idx + 40)):
            text = lines[idx]
            start = open_col if idx == line_idx else 0
            segment = text[start:]
            parts.append(segment)
            clean = strip_strings(segment.split("//", 1)[0])
            for ch in clean:
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth <= 0:
                        return "\n".join(parts)
            if depth <= 0 and idx > line_idx:
                return "\n".join(parts)
        return "\n".join(parts)

    def top_level_args(text: str) -> list[str]:
        body = text[text.find("(") + 1 :]
        args: list[str] = []
        start = 0
        depth = 0
        in_string = False
        pos = 0
        while pos < len(body):
            ch = body[pos]
            if in_string:
                if ch == '"':
                    if pos + 1 < len(body) and body[pos + 1] == '"':
                        pos += 2
                        continue
                    in_string = False
                pos += 1
                continue
            if ch == '"':
                in_string = True
            elif ch == "(":
                depth += 1
            elif ch == ")":
                if depth == 0:
                    args.append(body[start:pos])
                    return args
                depth -= 1
            elif ch == "," and depth == 0:
                args.append(body[start:pos])
                start = pos + 1
            pos += 1
        args.append(body[start:])
        return args

    for line_idx, line in enumerate(lines):
        if line.lstrip().startswith("//"):
            continue
        line_folded = line.casefold()
        if not (
            "стрзаменить" in line_folded
            or "strreplace" in line_folded
            or "вставить" in line_folded
            or "insert" in line_folded
        ):
            continue
        for match in call_start_re.finditer(line):
            name = match.group("name")
            if name.casefold() not in fallback_names:
                continue
            if (line_idx, match.start("name")) in seen:
                continue
            text = call_text_from(line_idx, match.end() - 1)
            if "\n" not in text:
                continue
            multiline_params = [arg for arg in top_level_args(text) if "\n" in arg.strip()]
            if not multiline_params:
                continue
            if not any(
                nested_match.group(1).casefold() not in allowed_names
                for param in multiline_params
                for nested_match in nested_call_re.finditer(strip_strings(param))
            ):
                continue
            diags.append(
                _diag.Diagnostic(
                    file=path,
                    line=line_idx + 1,
                    character=match.start("name"),
                    end_line=line_idx + 1,
                    end_character=match.end("name"),
                    severity=_diag.Severity.INFORMATION,
                    code="BSL224",
                )
            )
    return diags


def run_bsl240_rewrite_method_parameter(
    path: str,
    lines: list[str],
    procs: list[_ProcInfo],
    tree: Any,
    proc_node_map: dict[tuple[str, int, str], Any] | None = None,
) -> list[Any]:
    _diag = _diag_module()
    diags: list[Any] = []
    tree_ok = _diag._ts_tree_ok_for_rules(tree)
    if not tree_ok:
        return []
    for proc in procs:
        body_start = proc.start_idx + 1
        pnode = _method_proc_node(_diag, tree, proc, proc_node_map)
        if pnode is None:
            continue
        bl = _diag._ts_first_body_statement_line_idx(pnode)
        if bl is not None and bl > proc.start_idx:
            body_start = bl

        if body_start >= proc.end_idx:
            continue

        val_cf = {n.casefold() for n in (getattr(proc, "val_params", None) or [])}
        if not val_cf:
            continue
        used_before_assign: set[str] = set()

        assignment_items = _bsl240_assignment_items_from_cst(_diag, pnode)

        for li, lhs_text, rhs_text, start_char, end_char, line_text in assignment_items:
            if li >= len(lines):
                break
            lhs = lhs_text.casefold()
            if lhs in val_cf:
                if lhs not in rhs_text.casefold() and lhs not in used_before_assign:
                    diags.append(
                        _diag.Diagnostic(
                            file=path,
                            line=li + 1,
                            character=start_char,
                            end_line=li + 1,
                            end_character=end_char,
                            severity=_diag.Severity.WARNING,
                            code="BSL240",
                        )
                    )
                elif lhs in rhs_text.casefold():
                    used_before_assign.add(lhs)
            for param_cf in val_cf:
                if param_cf != lhs and re.search(
                    rf"\b{re.escape(param_cf)}\b", line_text, re.IGNORECASE
                ):
                    used_before_assign.add(param_cf)
    return diags


def _method_proc_node(
    _diag: Any,
    tree: Any,
    proc: _ProcInfo,
    proc_node_map: dict[tuple[str, int, str], Any] | None,
) -> Any | None:
    key = (proc.name, proc.start_idx, getattr(proc, "kind", "procedure"))
    return (
        proc_node_map.get(key)
        if proc_node_map is not None
        else _diag._find_proc_definition_node(tree, proc)
    )


def _assigned_names_from_cst(_diag: Any, proc_node: Any) -> set[str]:
    return {item[1].casefold() for item in _bsl240_assignment_items_from_cst(_diag, proc_node)}


def _bsl240_assignment_items_from_cst(
    _diag: Any, proc_node: Any
) -> list[tuple[int, str, str, int, int, str]]:
    items: list[tuple[int, str, str, int, int, str]] = []
    for node in _diag._ts_walk(proc_node):
        if getattr(node, "type", None) != "assignment_statement":
            continue
        children = list(getattr(node, "children", []) or [])
        if not children or getattr(children[0], "type", None) != "identifier":
            continue
        lhs_node = children[0]
        rhs_node = next((c for c in children if getattr(c, "type", None) == "expression"), None)
        lhs_text = _diag._ts_node_text(lhs_node)
        rhs_text = _diag._ts_node_text(rhs_node) if rhs_node is not None else ""
        line_idx = lhs_node.start_point[0]
        line_text = _diag._ts_node_text(node)
        items.append(
            (
                line_idx,
                lhs_text,
                rhs_text,
                lhs_node.start_point[1],
                lhs_node.end_point[1],
                line_text,
            )
        )
    return sorted(items, key=lambda item: (item[0], item[3]))
