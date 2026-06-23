from __future__ import annotations

import re
from typing import Any


def _diag_module() -> Any:
    from onec_hbk_bsl.analysis import diagnostics as _diag

    return _diag


def _query_block_has_escaped_empty_query_string(
    content_lines: list[tuple[int, int, str, str, bool]],
) -> bool:
    return any('""""' in content for _, _, content, _, _ in content_lines)


def _query_block_has_escaped_empty_comparison_tail(last_content: str) -> bool:
    return bool(re.search(r"(?:=|<>)\s*\"{4}", last_content))


def _bsl235_diag_from_sdbl_tree(path: str, block: Any) -> Any | None:
    if not getattr(block, "sdbl_has_errors", False):
        return None
    tree = getattr(block, "sdbl_tree", None)
    root = getattr(tree, "root_node", None)
    if root is None:
        return None

    start_line, start_char = block.original_lsp_position(root.start_point[0], root.start_point[1])
    end_line, end_char = block.original_lsp_position(root.end_point[0], root.end_point[1])
    if (end_line, end_char) <= (start_line, start_char):
        return None

    _diag = _diag_module()
    return _diag.Diagnostic(
        file=path,
        line=start_line + 1,
        character=start_char,
        end_line=end_line + 1,
        end_character=end_char,
        severity=_diag.Severity.WARNING,
        code="BSL235",
    )


def _bsl235_diag_from_content_lines(
    path: str, content_lines: list[tuple[int, int, str, str, bool]]
) -> Any:
    _diag = _diag_module()
    first_line_no, first_content_base, _first_content, _first_head, _ = content_lines[0]
    last_line_no, last_content_base, _last_content, last_head, _ = content_lines[-1]
    return _diag.Diagnostic(
        file=path,
        line=first_line_no,
        character=first_content_base,
        end_line=last_line_no,
        end_character=last_content_base + len(last_head),
        severity=_diag.Severity.WARNING,
        code="BSL235",
    )


def _unescape_bsl_query_head(head: str) -> tuple[str, list[int]]:
    """Return SDBL text for a query line and UTF-8 byte offset to BSL column map."""

    out: list[str] = []
    byte_to_original_col = [0]
    idx = 0
    while idx < len(head):
        if head[idx] == '"' and idx + 1 < len(head) and head[idx + 1] == '"':
            char = '"'
            original_end = idx + 1
            idx += 2
        else:
            char = head[idx]
            original_end = idx + 1
            idx += 1
        out.append(char)
        encoded_len = len(char.encode("utf-8"))
        byte_to_original_col.extend([original_end] * encoded_len)
    return "".join(out), byte_to_original_col


def _parse_unescaped_sdbl_query_text(block: Any) -> tuple[Any | None, list[list[int]]]:
    from onec_hbk_bsl.analysis import document_snapshot as _snapshot

    if _snapshot._SDBL_LANGUAGE is None or _snapshot._TsParser is None:
        return None, []

    unescaped_lines: list[str] = []
    byte_maps: list[list[int]] = []
    for line in getattr(block, "content_lines", ()) or ():
        unescaped, byte_map = _unescape_bsl_query_head(line.head)
        unescaped_lines.append(unescaped)
        byte_maps.append(byte_map)
    query_text = "\n".join(unescaped_lines)
    if not query_text.strip():
        return None, []

    parser = _snapshot._TsParser(_snapshot._SDBL_LANGUAGE)
    return parser.parse(query_text.encode("utf-8")), byte_maps


def _unescaped_lsp_position(
    block: Any,
    byte_maps: list[list[int]],
    row: int,
    utf8_col: int,
) -> tuple[int, int]:
    if row < 0 or row >= len(getattr(block, "content_lines", ())):
        return getattr(block, "start_idx", 0), 0
    line = block.content_lines[row]
    byte_map = byte_maps[row] if row < len(byte_maps) else []
    original_col = byte_map[min(max(utf8_col, 0), len(byte_map) - 1)] if byte_map else 0
    return line.line_no - 1, line.content_base + original_col


def _sdbl_string_nodes_from_root(root: Any) -> list[Any]:
    out: list[Any] = []

    def walk(node: Any) -> None:
        if getattr(node, "type", None) == "string":
            out.append(node)
            return
        for child in getattr(node, "children", ()) or ():
            walk(child)

    walk(root)
    return out


def _bsl220_diags_from_sdbl_tree(path: str, block: Any) -> list[Any]:
    tree, byte_maps = _parse_unescaped_sdbl_query_text(block)
    root = getattr(tree, "root_node", None)
    if root is None:
        return []

    _diag = _diag_module()
    diags: list[Any] = []
    for node in _sdbl_string_nodes_from_root(root):
        if node.start_point[0] == node.end_point[0]:
            continue
        start_line, start_character = _unescaped_lsp_position(
            block, byte_maps, node.start_point[0], node.start_point[1] + 1
        )
        end_line, end_character = _unescaped_lsp_position(
            block, byte_maps, node.end_point[0], node.end_point[1]
        )
        diags.append(
            _diag.Diagnostic(
                file=path,
                line=start_line + 1,
                character=start_character,
                end_line=end_line + 1,
                end_character=end_character,
                severity=_diag.Severity.INFORMATION,
                code="BSL220",
            )
        )
    return diags


def _query_block_has_root(block: Any) -> bool:
    tree = getattr(block, "sdbl_tree", None)
    return getattr(tree, "root_node", None) is not None


def run_bsl220_235_269_query_text_diagnostics(
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

        has_escaped_empty_query_string = _query_block_has_escaped_empty_query_string(content_lines)
        last_content = content_lines[-1][2]
        if (
            "BSL235" in enabled
            and not has_escaped_empty_query_string
            and not _query_block_has_escaped_empty_comparison_tail(last_content)
        ):
            has_legacy_parse_error = not _diag._query_has_balanced_parens(
                [head for _, _, _, head, _ in content_lines]
            ) or _has_plain_tail_parse_error(content_lines)
            sdbl_diag = _bsl235_diag_from_sdbl_tree(path, block)
            if has_legacy_parse_error and sdbl_diag is not None:
                diags.append(_bsl235_diag_from_content_lines(path, content_lines))
            elif _query_block_has_root(block):
                pass
            elif has_legacy_parse_error:
                diags.append(_bsl235_diag_from_content_lines(path, content_lines))

        if "BSL220" in enabled:
            diags.extend(_bsl220_diags_from_sdbl_tree(path, block))

        for line_no, content_base, _content, head, _ended_query in content_lines:
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
                        )
                    )
    if query_blocks is None:
        for start_idx, block_lines in _diag._iter_query_text_blocks(lines):
            content_lines = list(_diag._iter_query_text_content_lines(start_idx, block_lines))
            if not content_lines:
                continue

            has_escaped_empty_query_string = _query_block_has_escaped_empty_query_string(
                content_lines
            )
            last_content = content_lines[-1][2]
            if (
                "BSL235" in enabled
                and not has_escaped_empty_query_string
                and not _query_block_has_escaped_empty_comparison_tail(last_content)
                and (
                    not _diag._query_has_balanced_parens(
                        [head for _, _, _, head, _ in content_lines]
                    )
                    or _has_plain_tail_parse_error(content_lines)
                )
            ):
                line_no, content_base, _content, head, _ = content_lines[-1]
                diags.append(
                    _diag.Diagnostic(
                        file=path,
                        line=line_no,
                        character=content_base,
                        end_line=line_no,
                        end_character=content_base + len(head),
                        severity=_diag.Severity.WARNING,
                        code="BSL235",
                    )
                )

            for line_no, content_base, _content, head, _ended_query in content_lines:
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

        def has_join_before_query_end(lines_slice: list[Any], start_pos: int) -> bool:
            for _line_no, _content_base, _content, future_head, _ended_query in lines_slice[
                start_pos + 1 :
            ]:
                if (
                    ";" in future_head
                    or _diag._RE_QUERY_UNION_KEYWORD.search(future_head)
                    or _diag._RE_QUERY_SELECT_KEYWORD.search(future_head)
                ):
                    return False
                if _diag._RE_QUERY_JOIN_KEYWORD.search(future_head):
                    return True
            return False

        for pos, (line_no, content_base, _content, head, _ended_query) in enumerate(content_lines):
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
                            )
                        )
                if "BSL207" in enabled:
                    virtual_match = _diag._RE_QUERY_VIRTUAL_TABLE.search(head)
                    if virtual_match and (
                        join_datasource or has_join_before_query_end(content_lines, pos)
                    ):
                        end_character = content_base + len(head[: virtual_match.end()].rstrip())
                        open_idx = virtual_match.end() - 1
                        if open_idx >= 0 and head[open_idx] == "(":
                            close_idx = _diag._find_matching_paren(head, open_idx)
                            if close_idx > open_idx:
                                end_character = content_base + close_idx + 1
                        diags.append(
                            _diag.Diagnostic(
                                file=path,
                                line=line_no,
                                character=content_base + virtual_match.start(),
                                end_line=line_no,
                                end_character=end_character,
                                severity=_diag.Severity.WARNING,
                                code="BSL207",
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
                            )
                        )
    return diags
