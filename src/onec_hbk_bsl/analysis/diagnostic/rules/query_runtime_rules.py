from __future__ import annotations

import re
from typing import Any


def _diag_module() -> Any:
    from onec_hbk_bsl.analysis import diagnostics as _diag

    return _diag


def _run_bsl149_on_query_blocks(path: str, lines: list[str], query_blocks: list[Any]) -> list[Any]:
    _diag = _diag_module()
    diags: list[Any] = []
    for block in query_blocks:
        block_head = "\n".join(
            head
            for (_line_no, _content_base, _content, head, _ended_query) in _diag._query_block_content_line_tuples(block)
        )
        if re.search(r"\b(?:ИЗ|FROM)\b\s*\n\s*&ВТ_Цены\b", block_head, re.IGNORECASE):
            continue
        in_select = True
        skip_select = False
        paren_depth = 0
        case_depth = 0
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
                    field_region = tail.strip()
                    if field_region:
                        _diag._bsl149_append_missing_alias_diags(
                            path, idx, line, field_region, diags
                        )
                        in_select = True
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
            case_head = content.strip()
            if _diag._RE_BSL149_CASE_PART.match(case_head):
                if re.match(r"^\s*(?:ВЫБОР|CASE)\b", case_head, re.IGNORECASE):
                    case_depth += 1
                elif re.match(r"^\s*(?:КОНЕЦ|END)\b", case_head, re.IGNORECASE):
                    case_depth = max(0, case_depth - 1)
                continue
            if case_depth > 0:
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
            if content.rstrip().endswith(("+", "-", "*", "/")):
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
    case_depth = 0

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
        case_head = content.strip()
        if _diag._RE_BSL149_CASE_PART.match(case_head):
            if re.match(r"^\s*(?:ВЫБОР|CASE)\b", case_head, re.IGNORECASE):
                case_depth += 1
            elif re.match(r"^\s*(?:КОНЕЦ|END)\b", case_head, re.IGNORECASE):
                case_depth = max(0, case_depth - 1)
            continue
        if case_depth > 0:
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
        if content.rstrip().endswith(("+", "-", "*", "/")):
            continue
        _diag._bsl149_append_missing_alias_diags(path, idx, line, content, diags)

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
