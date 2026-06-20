from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

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
            for idx in range(proc.start_idx + 1, proc.end_idx + 1):
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
        if call.callee_args_count >= len(callee.params):
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
        diags.append(
            _diag.Diagnostic(
                file=path,
                line=call.caller_line,
                character=call.caller_character,
                end_line=call.caller_line,
                end_character=len(line_text.rstrip()),
                severity=_diag.Severity.ERROR,
                code="BSL212",
            )
        )
    return diags


def run_bsl215_missing_parameter_description(
    path: str,
    lines: list[str],
    procs: list[_ProcInfo],
) -> list[Any]:
    _diag = _diag_module()
    diags: list[Any] = []
    legacy_doc_path = bool(re.search(r"(?:ManagerModule|ObjectModule)\.bsl$", path))
    for proc in procs:
        block_end = proc.start_idx - 1
        while block_end >= 0 and _diag._RE_COMPILER_DIRECTIVE.match(lines[block_end]):
            block_end -= 1
        if block_end < 0 or not _diag._RE_BSL215_COMMENT_LINE.match(lines[block_end]):
            continue

        block_start = block_end
        while block_start > 0 and _diag._RE_BSL215_COMMENT_LINE.match(lines[block_start - 1]):
            block_start -= 1

        comment_block = lines[block_start : block_end + 1]
        if legacy_doc_path:
            comment_block = [
                re.sub(r"^(\s*//)\t ?", r"\1  ", cl).replace("\t", " ") for cl in comment_block
            ]
        re_separator = re.compile(r"^\s*/{10,}\s*$")
        if any(re_separator.match(cl) for cl in comment_block):
            continue
        if any(
            re.match(r"^\s*//\s*ВозвращаемоеЗначение\s*:?\s*$", cl, re.IGNORECASE)
            for cl in comment_block
        ):
            continue

        re_see_link = re.compile(r"^\s*//\s*(?:См\.|See)\s+\S", re.IGNORECASE)
        if any(re_see_link.match(cl) for cl in comment_block):
            continue

        # BSLLS treats any adjacent comment block as method documentation.
        # Blank/service one-line comments still establish the presence of a doc block,
        # after which missing parameter descriptions should be reported.
        if not any(cl.strip().startswith("//") for cl in comment_block):
            continue
        params_section_start = None
        for ci, cl in enumerate(comment_block):
            if _diag._RE_BSL215_PARAMS_SECTION.match(cl):
                params_section_start = ci
                break
        if params_section_start is None and any(
            re.match(
                r"^\s*//\s*(?:Состав\s+структуры)\s*:?\s*$",
                cl,
                re.IGNORECASE,
            )
            for cl in comment_block
        ):
            continue
        if params_section_start is None and len(comment_block) == 1:
            text = re.sub(r"^\s*//\s*", "", comment_block[0]).strip()
            if re.match(r"^(?:Конец|End)\b", text, re.IGNORECASE):
                continue
            if text and text[0].islower():
                continue

        actual_params_cf = {p.casefold() for p in proc.params}
        try:
            header_col = lines[proc.start_idx].index(proc.name)
        except ValueError:
            header_col = 0

        if params_section_start is None:
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

        def _has_bslls_type_description(tail: str) -> bool:
            if legacy_doc_path:
                tail = re.sub(r"\t+", " ", tail)
            if re.match(
                r"^\s*(?:см\.|see)\s+([A-Za-zА-ЯЁа-яё_]\w*(?:\.\w+)+)[.;]?\s*$",
                tail,
                re.IGNORECASE,
            ):
                return True
            type_text = re.split(r"\s+-\s+", tail, maxsplit=1)[0].strip()
            if not type_text or "\t" in type_text:
                return False
            type_text = type_text.rstrip()
            if type_text.endswith(","):
                type_text = type_text[:-1].rstrip()
            if legacy_doc_path and type_text.endswith("-"):
                type_text = type_text[:-1].rstrip()
            if type_text.endswith(":"):
                type_text = type_text[:-1].rstrip()
            elif type_text.rstrip() != type_text.rstrip(".;"):
                return False
            if type_text.casefold() in {"структура", "structure"}:
                return True
            if re.fullmatch(
                r"(?:Массив|Array)\s+(?:Из|Of)\s+[A-ZА-ЯЁ][\w]*(?:\.[A-ZА-ЯЁ]\w*)*",
                type_text,
                re.IGNORECASE,
            ):
                return legacy_doc_path or bool(
                    re.fullmatch(
                        r"(?:Массив|Array)\s+(?:Из|Of)\s+(?:Структура|Structure)",
                        type_text,
                        re.IGNORECASE,
                    )
                )
            if re.search(r"\b(?:или|or|элементов|element)\b", type_text, re.IGNORECASE):
                return False
            if re.search(r"[A-Za-zА-ЯЁа-яё0-9_]\s+[A-Za-zА-ЯЁа-яё0-9_]", type_text):
                return False
            type_name = r"[A-ZА-ЯЁ][\w]*(?:\.[A-ZА-ЯЁ]\w*)*"
            return bool(
                re.fullmatch(rf"{type_name}(?:\s*,\s*{type_name})*", type_text)
                or re.fullmatch(r"[a-zа-яё]+", type_text)
            )

        raw_param_entries: list[tuple[int, str, str]] = []
        for cl in comment_block[params_section_start + 1 :]:
            stripped = cl.strip()
            if stripped == "//" or (
                re.match(r"^\s*//\s*\w[\w\s]*:\s*$", cl)
                and not _diag._RE_BSL215_PARAM_ENTRY.match(cl)
            ):
                break
            if re.match(r"^\s*//\s+\*", cl):
                continue
            m = re.match(
                r"^\s*//(?P<indent>[ \t]{1,8})(?P<name>\w+)\s*-\s*(?P<tail>.+?)\s*$",
                cl,
                re.UNICODE,
            )
            if (
                m
                and (legacy_doc_path or not m.group("indent").startswith("\t"))
                and _has_bslls_type_description(m.group("tail"))
            ):
                raw_param_entries.append((len(m.group("indent")), m.group("name"), m.group("tail")))
        param_entry_indent = min((indent for indent, _name, _tail in raw_param_entries), default=0)

        def _param_entry(
            line: str,
            entry_indent: int = param_entry_indent,
        ) -> tuple[str, bool, str | None] | None:
            m = re.match(
                r"^\s*//(?P<indent>[ \t]{1,8})(?P<name>\w+)\s*-\s*(?P<tail>.+?)\s*$",
                line,
                re.UNICODE,
            )
            if not m:
                return None
            if m.group("indent").startswith("\t") and not legacy_doc_path:
                return None
            if entry_indent and len(m.group("indent")) != entry_indent:
                return None
            tail = m.group("tail")
            if not _has_bslls_type_description(tail):
                return None
            reference_match = re.match(
                r"^\s*(?:см\.|see)\s+([A-Za-zА-ЯЁа-яё_]\w*(?:\.\w+)+)[.;]?\s*$",
                tail,
                re.IGNORECASE,
            )
            if reference_match is not None and tail.rstrip().endswith((".", ";")):
                return (
                    reference_match.group(1).rstrip(".;"),
                    True,
                    reference_match.group(1).rstrip(".;"),
                )
            return m.group("name"), True, None

        documented_entries: list[str] = []
        empty_description_entries: set[str] = set()
        stale_reference_entries: list[str] = []
        for cl in comment_block[params_section_start + 1 :]:
            stripped = cl.strip()
            if stripped == "//" or (
                re.match(r"^\s*//\s*\w[\w\s]*:\s*$", cl)
                and not _diag._RE_BSL215_PARAM_ENTRY.match(cl)
            ):
                break
            if re.match(r"^\s*//\s+\*", cl):
                continue
            entry = _param_entry(cl)
            if entry:
                pname, has_type_description, stale_reference = entry
                if not has_type_description:
                    empty_description_entries.add(pname.casefold())
                documented_entries.append(pname)

        documented_cf = {p.casefold(): p for p in documented_entries}
        for actual_param in proc.params:
            if actual_param.casefold() in documented_cf:
                continue
            if legacy_doc_path and any(
                re.search(r"^\s*// [ \t]*" + re.escape(actual_param) + r"\s*-", cl, re.IGNORECASE)
                and not re.search(r"\s-\s*(?:см\.|see)\s+\S+[.;]\s*$", cl, re.IGNORECASE)
                for cl in comment_block[params_section_start + 1 :]
            ):
                documented_entries.append(actual_param)
                documented_cf[actual_param.casefold()] = actual_param
        force_all_params_missing = bool(
            proc.params
            and any(re.search(r"\(\s*пример\s+см\.", cl, re.IGNORECASE) for cl in comment_block)
        )

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
            and raw_param_entries
            and " - " not in raw_param_entries[0][2]
            and "," not in raw_param_entries[0][2]
            and not re.match(r"^\s*(?:см\.|see)\s+", raw_param_entries[0][2], re.IGNORECASE)
            and not raw_param_entries[0][2].strip().endswith(":")
            and (
                not legacy_doc_path
                or raw_param_entries[0][2].strip().casefold()
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
        if force_all_params_missing:
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
                if param_line_idx != proc.start_idx and pl.startswith("\t\t") and col > 0:
                    col -= 1
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

        block_end = proc.start_idx - 1
        while block_end >= 0 and (
            lines[block_end].strip() == "" or _diag._RE_COMPILER_DIRECTIVE.match(lines[block_end])
        ):
            block_end -= 1

        has_description = block_end >= 0 and _diag._RE_BSL215_COMMENT_LINE.match(lines[block_end])
        if has_description:
            blk_s = block_end
            while blk_s > 0 and _diag._RE_BSL215_COMMENT_LINE.match(lines[blk_s - 1]):
                blk_s -= 1
            block = lines[blk_s : block_end + 1]
            if any(re.match(r"^\s*/{10,}\s*$", cl) for cl in block):
                has_description = False

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
