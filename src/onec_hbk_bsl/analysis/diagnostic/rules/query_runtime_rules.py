from __future__ import annotations

import re
from bisect import bisect_left
from typing import Any


def _diag_module() -> Any:
    from onec_hbk_bsl.analysis import diagnostics as _diag

    return _diag


def _run_bsl149_on_query_blocks(path: str, lines: list[str], query_blocks: list[Any]) -> list[Any]:
    _diag = _diag_module()
    diags: list[Any] = []
    for block in query_blocks:
        in_select = True
        skip_select = False
        paren_depth = 0
        first_content_line = True
        for (
            line_no,
            _content_base,
            _content,
            head,
            _ended_query,
        ) in _diag._query_block_content_line_tuples(block):
            idx = line_no - 1
            line = lines[idx]
            content = head

            if first_content_line:
                first_content_line = False
                m_sel = _diag._RE_BSL149_SELECT.search(content)
                if m_sel:
                    tail = content[m_sel.end() :]
                    m_clause = _diag._RE_BSL149_CLAUSE_AFTER_FIELDS.search(tail)
                    if m_clause:
                        field_region = tail[: m_clause.start()].strip()
                        _diag._bsl149_append_missing_alias_diags(
                            path, idx, line, field_region, diags
                        )
                        in_select = False
                        continue

            if ";" in content:
                in_select = False
                skip_select = False
                paren_depth = 0
                after_semi = content[content.index(";") + 1 :].strip()
                if _diag._RE_BSL149_SELECT.search(after_semi):
                    in_select = not skip_select
                    skip_select = False
                continue

            if not content:
                continue
            if _diag._RE_BSL149_UNION.search(content):
                in_select = False
                skip_select = True
                continue
            if _diag._RE_BSL149_SELECT.search(content):
                m = _diag._RE_BSL149_SELECT.search(content)
                before_select = content[: m.start()]
                paren_depth += before_select.count("(") - before_select.count(")")
                if skip_select:
                    in_select = False
                elif paren_depth > 0:
                    in_select = True
                else:
                    in_select = not skip_select
                    skip_select = False
                continue
            if _diag._RE_BSL149_CLAUSE_END.match(content):
                paren_depth += content.count("(") - content.count(")")
                if paren_depth < 0:
                    paren_depth = 0
                in_select = False
                continue
            if ")" in content and paren_depth > 0:
                paren_depth -= content.count(")")
                paren_depth += content.count("(")
                if paren_depth < 0:
                    paren_depth = 0
                in_select = False
                continue
            if not in_select:
                continue
            _diag._bsl149_append_missing_alias_diags(path, idx, line, content, diags)
    return diags


def run_bsl149_assign_alias_fields_in_query(
    path: str, lines: list[str], query_blocks: list[Any] | None = None
) -> list[Any]:
    _diag = _diag_module()
    if query_blocks is not None:
        return _run_bsl149_on_query_blocks(path, lines, query_blocks)
    diags: list[Any] = []
    in_query = False
    in_select = False
    skip_select = False
    paren_depth = 0

    for idx, line in enumerate(lines):
        stripped = line.rstrip()
        if not _diag._RE_BSL149_CONTINUATION.match(stripped):
            if in_query:
                in_query = False
                in_select = False
                skip_select = False
                paren_depth = 0
            m_sel = _diag._RE_BSL149_SELECT.search(stripped)
            if m_sel:
                tail = stripped[m_sel.end() :]
                m_clause = _diag._RE_BSL149_CLAUSE_AFTER_FIELDS.search(tail)
                if m_clause:
                    field_region = tail[: m_clause.start()]
                    qpos = field_region.find('"')
                    if qpos >= 0:
                        field_region = field_region[:qpos]
                    field_region = _diag._RE_BSL149_INLINE_COMMENT.sub("", field_region).strip()
                    _diag._bsl149_append_missing_alias_diags(path, idx, line, field_region, diags)
                else:
                    in_query = True
                    in_select = True
                    skip_select = False
                    paren_depth = 0
            continue

        if not in_query:
            if _diag._RE_BSL149_SELECT.search(stripped):
                in_query = True
                in_select = True
                skip_select = False
                paren_depth = 0
            else:
                continue

        raw_content = stripped.lstrip()
        if raw_content.startswith("|"):
            raw_content = raw_content[1:]
        content = _diag._RE_BSL149_INLINE_COMMENT.sub("", raw_content).rstrip()

        if ";" in content:
            in_select = False
            skip_select = False
            paren_depth = 0
            after_semi = content[content.index(";") + 1 :].strip()
            if _diag._RE_BSL149_SELECT.search(after_semi):
                in_select = not skip_select
                skip_select = False
            continue

        if '"' in content:
            in_query = False
            in_select = False
            skip_select = False
            paren_depth = 0
            continue
        if not content:
            continue
        if _diag._RE_BSL149_UNION.search(content):
            in_select = False
            skip_select = True
            continue
        if _diag._RE_BSL149_SELECT.search(content):
            m = _diag._RE_BSL149_SELECT.search(content)
            before_select = content[: m.start()]
            paren_depth += before_select.count("(") - before_select.count(")")
            if skip_select:
                in_select = False
            elif paren_depth > 0:
                in_select = True
            else:
                in_select = not skip_select
                skip_select = False
            continue
        if _diag._RE_BSL149_CLAUSE_END.match(content):
            paren_depth += content.count("(") - content.count(")")
            if paren_depth < 0:
                paren_depth = 0
            in_select = False
            continue
        if ")" in content and paren_depth > 0:
            paren_depth -= content.count(")")
            paren_depth += content.count("(")
            if paren_depth < 0:
                paren_depth = 0
            in_select = False
            continue
        if not in_select:
            continue
        _diag._bsl149_append_missing_alias_diags(path, idx, line, content, diags)

    return diags


def run_bsl210_logical_or_in_where(path: str, lines: list[str]) -> list[Any]:
    _diag = _diag_module()
    diags: list[Any] = []
    in_query = False
    gp = 0
    where_stack: list[int] = []

    for idx, line in enumerate(lines):
        stripped = line.rstrip()
        if not _diag._RE_BSL149_CONTINUATION.match(stripped):
            if in_query:
                in_query = False
                gp = 0
                where_stack.clear()
            diags.extend(run_bsl210_scan_line_literal_queries(path, idx, line))
            m_sel = _diag._RE_BSL149_SELECT.search(stripped)
            if m_sel:
                tail = stripped[m_sel.end() :]
                if not _diag._RE_BSL149_CLAUSE_AFTER_FIELDS.search(tail):
                    in_query = True
                    gp = 0
                    where_stack.clear()
            continue

        if not in_query:
            if _diag._RE_BSL149_SELECT.search(stripped):
                in_query = True
                gp = 0
                where_stack.clear()
            else:
                continue

        raw_content = stripped.lstrip()
        if raw_content.startswith("|"):
            raw_content = raw_content[1:]
        content = _diag._RE_BSL149_INLINE_COMMENT.sub("", raw_content).rstrip()
        content = content.lstrip()

        line_rs = line.rstrip()
        pipe_pos = line_rs.find("|")
        if pipe_pos < 0:
            continue
        after_pipe = line_rs[pipe_pos + 1 :]
        leading_ws = len(after_pipe) - len(after_pipe.lstrip())
        content_base = pipe_pos + 1 + leading_ws

        quote_pos = content.find('"')
        ended_query = quote_pos >= 0
        content_scan = content[:quote_pos].rstrip() if ended_query else content
        tail_has_semi = ";" in content_scan
        head = content_scan[: content_scan.index(";")].rstrip() if tail_has_semi else content_scan

        if tail_has_semi and not head:
            where_stack.clear()
            gp = 0
            if ended_query:
                in_query = False
            continue
        if not head:
            if ended_query:
                in_query = False
                gp = 0
                where_stack.clear()
            continue
        if _diag._RE_BSL149_UNION.search(head):
            where_stack.clear()
            continue
        if where_stack and _diag._RE_BSL210_LINE_ENDS_WHERE.match(head):
            if gp == where_stack[-1]:
                where_stack.pop()
        if _diag._RE_BSL210_LINE_IS_WHERE.match(head):
            where_stack.append(gp)
        if where_stack:
            for om in _diag._RE_BSL210_OR.finditer(head):
                diags.append(
                    _diag.Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=content_base + om.start(),
                        end_line=idx + 1,
                        end_character=content_base + om.end(),
                        severity=_diag.Severity.WARNING,
                        code="BSL210",
                        message=_diag._BSL210_MESSAGE,
                    )
                )

        gp += head.count("(") - head.count(")")
        if gp < 0:
            gp = 0
        while where_stack and gp < where_stack[-1]:
            where_stack.pop()
        if tail_has_semi:
            where_stack.clear()
            gp = 0
        if ended_query:
            in_query = False
            gp = 0
            where_stack.clear()

    return diags


def run_bsl210_scan_line_literal_queries(path: str, idx: int, line: str) -> list[Any]:
    _diag = _diag_module()
    if _diag._RE_COMMENT_LINE.match(line):
        return []
    diags: list[Any] = []
    for quote_pos, literal in _diag._bsl210_iter_double_quoted_segments(line):
        if not (_diag._RE_BSL149_SELECT.search(literal) and _diag._RE_QUERY_WHERE.search(literal)):
            continue
        offset_base = 0
        for part in literal.split(";"):
            for start, end in _diag._bsl210_or_spans_in_query_literal(part):
                diags.append(
                    _diag.Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=quote_pos + 1 + offset_base + start,
                        end_line=idx + 1,
                        end_character=quote_pos + 1 + offset_base + end,
                        severity=_diag.Severity.WARNING,
                        code="BSL210",
                        message=_diag._BSL210_MESSAGE,
                    )
                )
            offset_base += len(part) + 1
    return diags


def run_bsl258_union_without_all(path: str, lines: list[str]) -> list[Any]:
    _diag = _diag_module()
    diags: list[Any] = []
    re_union = re.compile(r"\b(?:ОБЪЕДИНИТЬ|UNION)\b(?!\s+(?:ВСЕ|ALL)\b)", re.IGNORECASE)
    in_query = False
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("//"):
            continue
        if '|"' in line or line.strip().startswith("|"):
            in_query = True
        if stripped.endswith('";') or (stripped.endswith('"') and "ВЫБРАТЬ" not in stripped):
            in_query = False
        if not in_query and "|" not in line and '"' not in line:
            continue
        m = re_union.search(line)
        if m:
            diags.append(
                _diag.Diagnostic(
                    file=path,
                    line=idx + 1,
                    character=m.start(),
                    end_line=idx + 1,
                    end_character=m.end(),
                    severity=_diag.Severity.INFORMATION,
                    code="BSL258",
                    message="Замените конструкцию ОБЪЕДИНИТЬ на ОБЪЕДИНИТЬ ВСЕ",
                )
            )
    return diags


def run_bsl234_query_nested_fields_by_dot(path: str, lines: list[str]) -> list[Any]:
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
    metadata_roots = {
        "документ",
        "document",
        "справочник",
        "catalog",
        "перечисление",
        "enum",
        "регистрсведений",
        "informationregister",
        "регистрнакопления",
        "accumulationregister",
        "регистрбухгалтерии",
        "accountingregister",
        "плансчетов",
        "chartofaccounts",
        "планвидовхарактеристик",
        "chartofcharacteristictypes",
        "планрасчетавидов",
        "chartofcalculationtypes",
    }

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
                message="Обнаружено разыменование ссылочного поля",
            )
        )

    for line_no, line in enumerate(lines, start=1):
        stripped = line.lstrip()
        if not stripped.startswith("|"):
            in_group_by = False
            in_where = False
            continue
        masked = mask_value_calls(line)
        query_text = stripped[1:].strip()
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
                if root in metadata_roots:
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
                if first in metadata_roots:
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
                diags.append(
                    _diag.Diagnostic(
                        file=path,
                        line=line_no,
                        character=match.start(),
                        end_line=line_no,
                        end_character=match.end() - 1,
                        severity=_diag.Severity.INFORMATION,
                        code="BSL237",
                        message="Избавьтесь от избыточного обращения внутри модуля через его имя или псевдоним ЭтотОбъект",
                    )
                )
    return diags


def run_bsl245_server_side_export_form_method(
    path: str, lines: list[str], procs: list[Any]
) -> list[Any]:
    _diag = _diag_module()
    if not _diag.path_is_likely_form_module_bsl(path):
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
                message="Запрещено создавать серверные экспортные методы в форме",
            )
        )
    return diags


def _node_contains(parent: Any, child: Any) -> bool:
    start = getattr(parent, "start_byte", None)
    end = getattr(parent, "end_byte", None)
    child_start = getattr(child, "start_byte", None)
    if start is None or end is None or child_start is None:
        return False
    return start <= child_start < end


def _calls_in_node(
    parent: Any,
    calls: list[dict[str, Any]],
    starts: list[int] | None = None,
) -> list[dict[str, Any]]:
    start = getattr(parent, "start_byte", None)
    end = getattr(parent, "end_byte", None)
    if start is None or end is None:
        return [call for call in calls if _node_contains(parent, call["node"])]
    effective_starts = (
        starts
        if starts is not None
        else [getattr(call["node"], "start_byte", -1) for call in calls]
    )
    left = bisect_left(effective_starts, start)
    right = bisect_left(effective_starts, end)
    return calls[left:right]


def run_bsl262_usage_write_log_event(
    path: str,
    tree: Any,
    global_calls: list[dict[str, Any]] | None = None,
    global_call_starts: list[int] | None = None,
    try_nodes: list[Any] | None = None,
    line_texts: list[str] | None = None,
) -> list[Any]:
    _diag = _diag_module()
    root = getattr(tree, "root_node", None)
    if root is None or not isinstance(getattr(root, "text", None), (bytes, bytearray)):
        return []
    line_texts = line_texts if line_texts is not None else _diag._ts_node_text(root).splitlines()
    diags: list[Any] = []
    target_names = {"записьжурналарегистрации", "writelogevent"}
    level_root_names = {"уровеньжурналарегистрации", "eventloglevel"}
    error_level_names = {"ошибка", "error"}

    def except_children(try_node: Any) -> list[Any]:
        children = list(getattr(try_node, "children", []) or [])
        except_idx = next(
            (
                i
                for i, child in enumerate(children)
                if getattr(child, "type", None) == "EXCEPT_KEYWORD"
            ),
            None,
        )
        endtry_idx = next(
            (
                i
                for i, child in enumerate(children)
                if getattr(child, "type", None) == "ENDTRY_KEYWORD"
            ),
            None,
        )
        if except_idx is None:
            return []
        if endtry_idx is None:
            endtry_idx = len(children)
        return children[except_idx + 1 : endtry_idx]

    def arg_is_error_level(expr: Any) -> bool:
        text = _diag._ts_node_text(expr).casefold()
        return any(
            root_name in text and level in text
            for root_name in level_root_names
            for level in error_level_names
        )

    effective_try_nodes = (
        try_nodes
        if try_nodes is not None
        else [node for node in _diag._ts_walk(root) if getattr(node, "type", None) == "try_statement"]
    )
    for node in effective_try_nodes:
        for child in except_children(node):
            calls = (
                _calls_in_node(child, global_calls, global_call_starts)
                if global_calls is not None
                else _diag._ts_global_method_calls(child, line_texts)
            )
            for call in calls:
                if str(call["name"]).casefold() not in target_names:
                    continue
                args = _diag._ts_method_call_arg_exprs(call["node"])
                if len(args) < 2:
                    continue
                if arg_is_error_level(args[1]):
                    continue
                diags.append(
                    _diag.Diagnostic(
                        file=path,
                        line=call["line"],
                        character=call["character"],
                        end_line=call["line"],
                        end_character=call["end_character"],
                        severity=_diag.Severity.INFORMATION,
                        code="BSL262",
                        message='Нужно указывать уровень "Ошибка" при записи в журнал регистрации внутри блока Исключение-КонецПопытки',
                    )
                )
    return diags
