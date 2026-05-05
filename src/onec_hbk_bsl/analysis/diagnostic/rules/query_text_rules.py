from __future__ import annotations

import re
from typing import Any


def _diag_module() -> Any:
    from onec_hbk_bsl.analysis import diagnostics as _diag

    return _diag


def run_bsl220_235_269_273_query_text_diagnostics(
    path: str,
    lines: list[str],
    codes: tuple[str, ...],
    rule_enabled: Any,
    query_blocks: list[Any] | None = None,
) -> list[Any]:
    _diag = _diag_module()
    enabled = {code for code in codes if rule_enabled(code)}
    if not enabled:
        return []

    diags: list[Any] = []

    def _has_plain_tail_parse_error(
        content_lines: list[tuple[int, int, str, str, bool]],
    ) -> bool:
        line_no, content_base, content, head, ended_query = content_lines[-1]
        _ = (line_no, content_base)
        if not ended_query:
            return False
        tail = content.split('"', 1)[1].strip() if '"' in content else ""
        if tail not in {"", ";"}:
            return False
        if re.search(r"(?:=|<>)\s*\"{4}", content):
            return False
        return bool(
            _diag._RE_QUERY_PARSE_ERROR_TAIL_KEYWORD.search(head)
            or _diag._RE_QUERY_PARSE_ERROR_TAIL_OPERATOR.search(head)
        )

    if query_blocks is None:
        blocks_iter = None
    else:
        blocks_iter = query_blocks

    for block in blocks_iter or ():
        content_lines = _diag._query_block_content_line_tuples(block)
        if not content_lines:
            continue

        last_content = content_lines[-1][2]
        if "BSL235" in enabled and not re.search(r"(?:=|<>)\s*\"{4}", last_content) and (
            not _diag._query_has_balanced_parens([head for _, _, _, head, _ in content_lines])
            or _has_plain_tail_parse_error(content_lines)
        ):
            line_no, content_base, _content, head, _ = content_lines[-1]
            diags.append(
                _diag.Diagnostic(
                    file=path,
                    line=line_no,
                    character=content_base,
                    end_line=line_no,
                    end_character=content_base + len(head),
                    severity=_diag.Severity.ERROR,
                    code="BSL235",
                    message="Синтаксическая ошибка в тексте встроенного запроса",
                )
            )

        for line_no, content_base, content, head, _ended_query in content_lines:
            if "BSL220" in enabled:
                multi_match = re.search(r'"{4,}', content)
                if multi_match:
                    run = multi_match.group(0)
                    if len(run) == 4 and re.search(r"(?:=|<>)\s*\"{4}", content):
                        continue
                    diags.append(
                        _diag.Diagnostic(
                            file=path,
                            line=line_no,
                            character=content_base + multi_match.start(),
                            end_line=line_no,
                            end_character=content_base + multi_match.end(),
                            severity=_diag.Severity.INFORMATION,
                            code="BSL220",
                            message="Многострочная строка внутри текста запроса",
                        )
                    )

            if "BSL269" in enabled:
                for match in _diag._RE_QUERY_LIKE_OPERATOR.finditer(head):
                    diags.append(
                        _diag.Diagnostic(
                            file=path,
                            line=line_no,
                            character=content_base + match.start(),
                            end_line=line_no,
                            end_character=content_base + match.end(),
                            severity=_diag.Severity.INFORMATION,
                            code="BSL269",
                            message="Оператор ПОДОБНО может привести к полному сканированию таблицы",
                        )
                    )

            if "BSL273" in enabled:
                for match in _diag._RE_QUERY_VIRTUAL_TABLE_CALL.finditer(head):
                    open_match = match.group("open")
                    if open_match is None:
                        diags.append(
                            _diag.Diagnostic(
                                file=path,
                                line=line_no,
                                character=content_base + match.start("name"),
                                end_line=line_no,
                                end_character=content_base + match.end("name"),
                                severity=_diag.Severity.WARNING,
                                code="BSL273",
                                message="Обращение к виртуальной таблице без параметров",
                            )
                        )
                        continue

                    open_idx = match.end("open") - 1
                    close_idx = _diag._find_matching_paren(head, open_idx)
                    if close_idx < 0:
                        continue
                    args = head[open_idx + 1 : close_idx]
                    parts = [part.strip() for part in _diag._split_top_level_args(args)]
                    if not parts or all(not part for part in parts):
                        is_violation = True
                    elif len(parts) == 1:
                        is_violation = False
                    else:
                        is_violation = all(not part for part in parts[1:])
                    if is_violation:
                        diags.append(
                            _diag.Diagnostic(
                                file=path,
                                line=line_no,
                                character=content_base + match.start("name"),
                                end_line=line_no,
                                end_character=content_base + close_idx + 1,
                                severity=_diag.Severity.WARNING,
                                code="BSL273",
                                message="Обращение к виртуальной таблице без параметров",
                            )
                        )

    if query_blocks is None:
        for start_idx, block_lines in _diag._iter_query_text_blocks(lines):
            content_lines = list(_diag._iter_query_text_content_lines(start_idx, block_lines))
            if not content_lines:
                continue

            last_content = content_lines[-1][2]
            if "BSL235" in enabled and not re.search(r"(?:=|<>)\s*\"{4}", last_content) and (
                not _diag._query_has_balanced_parens([head for _, _, _, head, _ in content_lines])
                or _has_plain_tail_parse_error(content_lines)
            ):
                line_no, content_base, _content, head, _ = content_lines[-1]
                diags.append(
                    _diag.Diagnostic(
                        file=path,
                        line=line_no,
                        character=content_base,
                        end_line=line_no,
                        end_character=content_base + len(head),
                        severity=_diag.Severity.ERROR,
                        code="BSL235",
                        message="Синтаксическая ошибка в тексте встроенного запроса",
                    )
                )

            for line_no, content_base, content, head, _ended_query in content_lines:
                if "BSL220" in enabled:
                    multi_match = re.search(r'"{4,}', content)
                    if multi_match:
                        run = multi_match.group(0)
                        if len(run) == 4 and re.search(r"(?:=|<>)\s*\"{4}", content):
                            continue
                        diags.append(
                            _diag.Diagnostic(
                                file=path,
                                line=line_no,
                                character=content_base + multi_match.start(),
                                end_line=line_no,
                                end_character=content_base + multi_match.end(),
                                severity=_diag.Severity.INFORMATION,
                                code="BSL220",
                                message="Многострочная строка внутри текста запроса",
                            )
                        )

                if "BSL269" in enabled:
                    for match in _diag._RE_QUERY_LIKE_OPERATOR.finditer(head):
                        diags.append(
                            _diag.Diagnostic(
                                file=path,
                                line=line_no,
                                character=content_base + match.start(),
                                end_line=line_no,
                                end_character=content_base + match.end(),
                                severity=_diag.Severity.INFORMATION,
                                code="BSL269",
                                message="Оператор ПОДОБНО может привести к полному сканированию таблицы",
                            )
                        )

                if "BSL273" in enabled:
                    for match in _diag._RE_QUERY_VIRTUAL_TABLE_CALL.finditer(head):
                        open_match = match.group("open")
                        if open_match is None:
                            diags.append(
                                _diag.Diagnostic(
                                    file=path,
                                    line=line_no,
                                    character=content_base + match.start("name"),
                                    end_line=line_no,
                                    end_character=content_base + match.end("name"),
                                    severity=_diag.Severity.WARNING,
                                    code="BSL273",
                                    message="Обращение к виртуальной таблице без параметров",
                                )
                            )
                            continue

                        open_idx = match.end("open") - 1
                        close_idx = _diag._find_matching_paren(head, open_idx)
                        if close_idx < 0:
                            continue
                        args = head[open_idx + 1 : close_idx]
                        parts = [part.strip() for part in _diag._split_top_level_args(args)]
                        if not parts or all(not part for part in parts):
                            is_violation = True
                        elif len(parts) == 1:
                            is_violation = False
                        else:
                            is_violation = all(not part for part in parts[1:])
                        if is_violation:
                            diags.append(
                                _diag.Diagnostic(
                                    file=path,
                                    line=line_no,
                                    character=content_base + match.start("name"),
                                    end_line=line_no,
                                    end_character=content_base + close_idx + 1,
                                    severity=_diag.Severity.WARNING,
                                    code="BSL273",
                                    message="Обращение к виртуальной таблице без параметров",
                                )
                            )
    return diags


def run_bsl191_201_query_text_diagnostics(
    path: str,
    lines: list[str],
    codes: tuple[str, ...],
    rule_enabled: Any,
    query_blocks: list[Any] | None = None,
) -> list[Any]:
    _diag = _diag_module()
    enabled = {code for code in codes if rule_enabled(code)}
    if not enabled:
        return []

    diags: list[Any] = []
    if query_blocks is None:
        blocks = (
            (
                start_idx,
                list(_diag._iter_query_text_content_lines(start_idx, block_lines)),
            )
            for start_idx, block_lines in _diag._iter_query_text_blocks(lines)
        )
    else:
        blocks = (
            (
                block.start_idx,
                _diag._query_block_content_line_tuples(block),
            )
            for block in query_blocks
        )

    for _start_idx, content_lines in blocks:
        for line_no, content_base, _content, head, _ended_query in content_lines:
            if "BSL191" in enabled:
                for match in _diag._RE_QUERY_FULL_OUTER_JOIN.finditer(head):
                    diags.append(
                        _diag.Diagnostic(
                            file=path,
                            line=line_no,
                            character=content_base + match.start(),
                            end_line=line_no,
                            end_character=content_base + match.end(),
                            severity=_diag.Severity.WARNING,
                            code="BSL191",
                            message="Полное внешнее соединение в запросе",
                        )
                    )

            if "BSL201" in enabled:
                for match in _diag._RE_QUERY_LIKE_OPERATOR.finditer(head):
                    rhs = head[match.end() :].lstrip()
                    if not rhs:
                        continue
                    stop_match = _diag._RE_QUERY_LIKE_TAIL_STOP.search(rhs)
                    rhs = rhs[: stop_match.start()] if stop_match else rhs
                    rhs = rhs.strip()
                    if not rhs:
                        continue
                    if "&" in rhs or '"' in rhs:
                        continue
                    diags.append(
                        _diag.Diagnostic(
                            file=path,
                            line=line_no,
                            character=content_base + match.start(),
                            end_line=line_no,
                            end_character=content_base + match.end(),
                            severity=_diag.Severity.WARNING,
                            code="BSL201",
                            message="Некорректное использование ПОДОБНО в запросе",
                        )
                    )
    return diags


def run_bsl206_207_209_query_join_diagnostics(
    path: str,
    lines: list[str],
    codes: tuple[str, ...],
    rule_enabled: Any,
    query_blocks: list[Any] | None = None,
) -> list[Any]:
    _diag = _diag_module()
    enabled = {code for code in codes if rule_enabled(code)}
    if not enabled:
        return []

    diags: list[Any] = []
    if query_blocks is None:
        blocks = (
            (
                start_idx,
                list(block_lines),
                list(_diag._iter_query_text_content_lines(start_idx, block_lines)),
            )
            for start_idx, block_lines in _diag._iter_query_text_blocks(lines)
        )
    else:
        blocks = (
            (
                block.start_idx,
                list(block.block_lines),
                _diag._query_block_content_line_tuples(block),
            )
            for block in query_blocks
        )

    for _start_idx, block_lines, content_lines in blocks:
        if not any(_diag._RE_QUERY_JOIN_KEYWORD.search(line) for line in block_lines):
            continue

        pending_datasource = False
        pending_join_datasource = False
        join_on_active = False
        join_buffer = ""

        for line_no, content_base, _content, head, _ended_query in content_lines:
            if _diag._RE_QUERY_JOIN_END_KEYWORD.search(head):
                join_on_active = False
                join_buffer = ""
                pending_datasource = False
                pending_join_datasource = False

            same_line_datasource = bool(
                re.search(r"\b(?:ИЗ|FROM)\s*$", head, re.IGNORECASE)
                or re.search(r"\b(?:СОЕДИНЕНИЕ|JOIN)\s*$", head, re.IGNORECASE)
                or _diag._RE_QUERY_JOIN_KEYWORD.search(head)
                or re.search(r"\b(?:ИЗ|FROM)\s*(\(\s*(?:ВЫБРАТЬ|SELECT)\b)", head, re.IGNORECASE)
                or re.search(
                    r"\b(?:ИЗ|FROM)\s*(" + _diag._RE_QUERY_VIRTUAL_TABLE.pattern + r")",
                    head,
                    re.IGNORECASE,
                )
            )
            join_datasource = bool(
                pending_join_datasource
                or re.search(r"\b(?:СОЕДИНЕНИЕ|JOIN)\s*$", head, re.IGNORECASE)
                or _diag._RE_QUERY_JOIN_KEYWORD.search(head)
            )

            if pending_datasource or same_line_datasource:
                if "BSL206" in enabled and join_datasource:
                    subquery_match = _diag._RE_QUERY_DATASOURCE_SUBQUERY.search(head)
                    if subquery_match:
                        diags.append(
                            _diag.Diagnostic(
                                file=path,
                                line=line_no,
                                character=content_base + subquery_match.start(),
                                end_line=line_no,
                                end_character=content_base + subquery_match.end(),
                                severity=_diag.Severity.WARNING,
                                code="BSL206",
                                message="Соединение с подзапросом в запросе",
                            )
                        )
                if "BSL207" in enabled:
                    virtual_match = _diag._RE_QUERY_VIRTUAL_TABLE.search(head)
                    if virtual_match:
                        diags.append(
                            _diag.Diagnostic(
                                file=path,
                                line=line_no,
                                character=content_base + virtual_match.start(),
                                end_line=line_no,
                                end_character=content_base + virtual_match.end(),
                                severity=_diag.Severity.WARNING,
                                code="BSL207",
                                message="Соединение с виртуальной таблицей в запросе",
                            )
                        )

            pending_datasource = bool(
                re.search(r"\b(?:ИЗ|FROM)\s*$", head, re.IGNORECASE)
                or re.search(r"\b(?:СОЕДИНЕНИЕ|JOIN)\s*$", head, re.IGNORECASE)
                or _diag._RE_QUERY_JOIN_KEYWORD.search(head)
            ) and not _diag._RE_QUERY_ON_KEYWORD.search(head)
            pending_join_datasource = bool(
                re.search(r"\b(?:СОЕДИНЕНИЕ|JOIN)\s*$", head, re.IGNORECASE)
                or _diag._RE_QUERY_JOIN_KEYWORD.search(head)
            ) and not _diag._RE_QUERY_ON_KEYWORD.search(head)

            on_match = _diag._RE_QUERY_ON_KEYWORD.search(head)
            if on_match:
                join_on_active = True
                join_buffer = head[on_match.end() :]
            elif join_on_active:
                if _diag._RE_QUERY_JOIN_KEYWORD.search(head):
                    join_on_active = False
                    join_buffer = ""
                else:
                    join_buffer += " " + head

            if join_on_active and "BSL209" in enabled:
                fields = set(_diag._RE_QUERY_COLUMN_REF.findall(join_buffer))
                if len(fields) > 1:
                    for or_match in _diag._RE_BSL210_OR.finditer(head):
                        diags.append(
                            _diag.Diagnostic(
                                file=path,
                                line=line_no,
                                character=content_base + or_match.start(),
                                end_line=line_no,
                                end_character=content_base + or_match.end(),
                                severity=_diag.Severity.WARNING,
                                code="BSL209",
                                message="Обнаружен оператор 'ИЛИ' в условии соединения",
                            )
                        )

    return diags
