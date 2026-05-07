from __future__ import annotations

import re
from typing import Any


def _diag_module() -> Any:
    from onec_hbk_bsl.analysis import diagnostics as _diag

    return _diag


def run_bsl183_execute_external_code(path: str, lines: list[str]) -> list[Any]:
    _diag = _diag_module()
    diags: list[Any] = []
    re_exec = re.compile(
        r"(?<![.\w])(?:Выполнить|Execute)\s*\((.{0,80})\)", re.IGNORECASE | re.UNICODE
    )
    re_literal = re.compile(r'^\s*"[^"]*"\s*$')
    re_comment = re.compile(r"^\s*//")

    for idx, line in enumerate(lines):
        if re_comment.match(line):
            continue
        for match in re_exec.finditer(line):
            arg = match.group(1).strip()
            if not re_literal.match(arg):
                diags.append(
                    _diag.Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=match.start(),
                        end_line=idx + 1,
                        end_character=match.end(),
                        severity=_diag.Severity.WARNING,
                        code="BSL183",
                        message="«Выполнить()» с динамическим аргументом — потенциальная угроза безопасности",
                    )
                )
    return diags


def run_bsl218_missing_temporary_file_deletion(
    path: str,
    lines: list[str],
    tree: Any,
    global_calls: list[dict[str, Any]] | None = None,
) -> list[Any]:
    _diag = _diag_module()
    root = getattr(tree, "root_node", None)
    if root is None or not isinstance(getattr(root, "text", None), (bytes, bytearray)):
        return []

    line_texts = lines
    diags: list[Any] = []

    calls = global_calls if global_calls is not None else _diag._ts_global_method_calls(root, line_texts)
    for call in calls:
        if str(call["name"]).casefold() not in _diag._BSL218_GET_TEMP_NAMES:
            continue
        method_node = call["node"]
        assign_anc: Any | None = None
        cur: Any | None = method_node
        while cur is not None:
            if getattr(cur, "type", None) == "assignment_statement":
                assign_anc = cur
                break
            cur = getattr(cur, "parent", None)

        span = _diag._ts_method_identifier_span(method_node, line_texts)
        if span is None:
            continue
        line_1, char_1, end_ch = span

        if assign_anc is None:
            diags.append(
                _diag.Diagnostic(
                    file=path,
                    line=line_1,
                    character=char_1,
                    end_line=line_1,
                    end_character=end_ch,
                    severity=_diag.Severity.ERROR,
                    code="BSL218",
                    message="Нужно добавить удаление временного файла после использования",
                )
            )
            continue

        var_name = _diag._ts_assignment_lvalue_text(assign_anc)
        if not var_name:
            diags.append(
                _diag.Diagnostic(
                    file=path,
                    line=line_1,
                    character=char_1,
                    end_line=line_1,
                    end_character=end_ch,
                    severity=_diag.Severity.ERROR,
                    code="BSL218",
                    message="Нужно добавить удаление временного файла после использования",
                )
            )
            continue

        raw_parent = getattr(assign_anc, "parent", None)
        stmt_parent = _diag._ts_bsl218_skip_error_ancestor(raw_parent)
        if stmt_parent is None:
            diags.append(
                _diag.Diagnostic(
                    file=path,
                    line=line_1,
                    character=char_1,
                    end_line=line_1,
                    end_character=end_ch,
                    severity=_diag.Severity.ERROR,
                    code="BSL218",
                    message="Нужно добавить удаление временного файла после использования",
                )
            )
            continue

        roots = _diag._ts_bsl218_code_block_roots(stmt_parent)
        if not roots:
            diags.append(
                _diag.Diagnostic(
                    file=path,
                    line=line_1,
                    character=char_1,
                    end_line=line_1,
                    end_character=end_ch,
                    severity=_diag.Severity.ERROR,
                    code="BSL218",
                    message="Нужно добавить удаление временного файла после использования",
                )
            )
            continue

        if not _diag._ts_bsl218_block_has_deletion(roots, line_texts, line_1, var_name):
            diags.append(
                _diag.Diagnostic(
                    file=path,
                    line=line_1,
                    character=char_1,
                    end_line=line_1,
                    end_character=end_ch,
                    severity=_diag.Severity.ERROR,
                    code="BSL218",
                    message="Нужно добавить удаление временного файла после использования",
                )
            )

    return diags


def run_bsl257_unary_plus_in_concatenation(path: str, lines: list[str]) -> list[Any]:
    _diag = _diag_module()
    diags: list[Any] = []
    re_unary = re.compile(r'(?:"[^"]*"|\'[^\']*\'|\b\w+\b)\s*\+\s*\+', re.UNICODE)
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("//"):
            continue
        clean = _diag._RE_DOUBLE_QUOTED_STRING.sub('""', line)
        match = re_unary.search(clean)
        if match:
            diags.append(
                _diag.Diagnostic(
                    file=path,
                    line=idx + 1,
                    character=match.start(),
                    end_line=idx + 1,
                    end_character=match.end(),
                    severity=_diag.Severity.WARNING,
                    code="BSL257",
                    message="Унарный «+» перед значением при конкатенации — вероятно опечатка",
                )
            )
    return diags
