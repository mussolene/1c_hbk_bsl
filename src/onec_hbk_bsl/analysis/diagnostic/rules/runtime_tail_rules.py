from __future__ import annotations

import re
from typing import Any


def _diag_module() -> Any:
    from onec_hbk_bsl.analysis import diagnostics as _diag

    return _diag


def run_bsl178_deprecated_methods_8317(path: str, lines: list[str], tree: Any) -> list[Any]:
    _diag = _diag_module()
    root = getattr(tree, "root_node", None)
    if root is None or not isinstance(getattr(root, "text", None), (bytes, bytearray)):
        return []
    deprecated = {
        "краткоепредставлениеошибки",
        "brieferrordescription",
        "подробноепредставлениеошибки",
        "detailerrordescription",
        "показатьинформациюобошибке",
        "showerrorinfo",
    }
    diags: list[Any] = []
    for call in _diag._ts_global_method_calls(root, lines):
        name_cf = str(call["name"]).casefold()
        if name_cf not in deprecated:
            continue
        line_text = lines[call["line"] - 1] if 0 < call["line"] <= len(lines) else ""
        exact_start = line_text.find(str(call["name"]))
        start_char = exact_start if exact_start >= 0 else call["character"]
        diags.append(
            _diag.Diagnostic(
                file=path,
                line=call["line"],
                character=start_char,
                end_line=call["line"],
                end_character=start_char + len(str(call["name"])),
                severity=_diag.Severity.INFORMATION,
                code="BSL178",
                message=(
                    f'Метод "{call["name"]}" устарел. Следует использовать одноименный '
                    "метод объекта типа МенеджерОбработкиОшибок"
                ),
            )
        )
    return diags


def run_bsl186_extra_commas(path: str, lines: list[str]) -> list[Any]:
    _diag = _diag_module()
    diags: list[Any] = []
    for idx, line in enumerate(lines):
        if _diag._RE_LINE_COMMENT.match(line):
            continue
        clean = _diag._RE_DOUBLE_QUOTED_STRING.sub('""', line)
        comment_pos = clean.find("//")
        if comment_pos >= 0:
            clean = clean[:comment_pos]
        m = _diag._RE_BSL186_TRAILING_COMMA.search(clean)
        if m:
            diags.append(
                _diag.Diagnostic(
                    file=path,
                    line=idx + 1,
                    character=m.start(),
                    end_line=idx + 1,
                    end_character=m.start() + 1,
                    severity=_diag.Severity.WARNING,
                    code="BSL186",
                    message="Лишняя запятая перед закрывающей скобкой или точкой с запятой",
                )
            )
    return diags


def run_bsl197_if_else_duplicated_code_block(path: str, lines: list[str]) -> list[Any]:
    _diag = _diag_module()
    diags: list[Any] = []
    comment_re = re.compile(r"^\s*//")
    i = 0
    while i < len(lines):
        if not _diag._RE_BSL197_IF.match(lines[i]):
            i += 1
            continue
        branches: list[tuple[list[str], tuple[int, int, int] | None]] = []
        branch_start = i
        branch_header = lines[i]
        depth = 1
        j = i + 1
        current_body: list[str] = []

        def normalize_body(body: list[str]) -> list[str]:
            return [
                entry.strip() for entry in body if entry.strip() and not comment_re.match(entry)
            ]

        def diag_span_for_body(body: list[str], start: int, header: str) -> tuple[int, int, int]:
            for offset, raw in enumerate(body, start=1):
                stripped = raw.strip()
                if stripped and not comment_re.match(raw):
                    col = len(raw) - len(raw.lstrip())
                    return start + offset, col, len(raw.rstrip())
            col = len(header) - len(header.lstrip())
            return start, col, len(header.rstrip())

        while j < len(lines) and depth > 0:
            bl = lines[j]
            if _diag._RE_BSL197_IF.match(bl):
                depth += 1
            elif _diag._RE_BSL197_ENDIF.match(bl):
                depth -= 1
                if depth == 0:
                    branches.append(
                        (
                            normalize_body(current_body),
                            diag_span_for_body(current_body, branch_start, branch_header),
                        )
                    )
                    break
            if depth == 1 and (
                _diag._RE_BSL197_ELSEIF.match(bl) or _diag._RE_BSL197_ELSE.match(bl)
            ):
                branches.append(
                    (
                        normalize_body(current_body),
                        diag_span_for_body(current_body, branch_start, branch_header),
                    )
                )
                current_body = []
                branch_start = j
                branch_header = bl
            else:
                if depth == 1:
                    current_body.append(bl)
            j += 1

        seen: dict[str, tuple[int, int, int] | None] = {}
        reported: set[str] = set()
        for b_body, span in branches:
            if len(b_body) == 1 and re.match(
                r"^(?:Возврат|Return|Продолжить|Continue|Прервать|Break)\s*;?\s*$",
                b_body[0],
                re.IGNORECASE,
            ):
                continue
            key = "\n".join(b_body)
            if key and key in seen and key not in reported:
                first_span = seen[key]
                if first_span is None:
                    continue
                line_no, col, end_col = first_span
                diags.append(
                    _diag.Diagnostic(
                        file=path,
                        line=line_no + 1,
                        character=col,
                        end_line=line_no + 1,
                        end_character=end_col,
                            severity=_diag.Severity.INFORMATION,
                            code="BSL197",
                            message='Синтаксическая конструкция "Если...Тогда...ИначеЕсли..." содержит повторяющиеся блоки кода',
                        )
                    )
                reported.add(key)
            else:
                seen[key] = span
        i += 1
    return diags


def run_bsl198_if_else_duplicated_condition(path: str, lines: list[str]) -> list[Any]:
    _diag = _diag_module()
    diags: list[Any] = []
    i = 0
    while i < len(lines):
        m = _diag._RE_BSL198_IF_COND.match(lines[i])
        if not m:
            i += 1
            continue
        conditions: dict[str, int] = {m.group(1).strip().casefold(): i}
        depth = 1
        j = i + 1
        while j < len(lines) and depth > 0:
            bl = lines[j]
            if _diag._RE_BSL197_IF.match(bl):
                depth += 1
            elif _diag._RE_BSL197_ENDIF.match(bl):
                depth -= 1
            elif depth == 1:
                em = _diag._RE_BSL198_ELSEIF_COND.match(bl)
                if em:
                    cond = em.group(1).strip().casefold()
                    if cond in conditions:
                        diags.append(
                            _diag.Diagnostic(
                                file=path,
                                line=j + 1,
                                character=0,
                                end_line=j + 1,
                                end_character=len(bl),
                                severity=_diag.Severity.WARNING,
                                code="BSL198",
                                message=(
                                    f"Условие «ИначеЕсли» совпадает с условием "
                                    f"на строке {conditions[cond] + 1} — ветка недостижима"
                                ),
                            )
                        )
                    else:
                        conditions[cond] = j
            j += 1
        i = j + 1
    return diags


def run_bsl199_if_else_if_ends_with_else(path: str, lines: list[str]) -> list[Any]:
    _diag = _diag_module()
    diags: list[Any] = []
    re_if = re.compile(r"^\s*(?:Если|If)\b", re.IGNORECASE)
    re_elseif = re.compile(r"^\s*(?:ИначеЕсли|ElseIf)\b", re.IGNORECASE)
    re_else = re.compile(r"^\s*(?:Иначе|Else)\b(?!\s*(?:Если|If)\b)", re.IGNORECASE)
    re_endif = re.compile(r"^\s*(?:КонецЕсли|EndIf)\b", re.IGNORECASE)
    i = 0
    while i < len(lines):
        if not re_if.match(lines[i]):
            i += 1
            continue
        has_elseif = False
        has_else = False
        depth = 1
        j = i + 1
        while j < len(lines) and depth > 0:
            bl = lines[j]
            if re_if.match(bl):
                depth += 1
            elif re_endif.match(bl):
                depth -= 1
            elif depth == 1:
                if re_elseif.match(bl):
                    has_elseif = True
                elif re_else.match(bl):
                    has_else = True
            j += 1
        if has_elseif and not has_else:
            endif_idx = j - 1
            if 0 <= endif_idx < len(lines):
                el = lines[endif_idx]
                char = len(el) - len(el.lstrip())
                diags.append(
                    _diag.Diagnostic(
                        file=path,
                        line=endif_idx + 1,
                        character=char,
                        end_line=endif_idx + 1,
                        end_character=len(el),
                        severity=_diag.Severity.WARNING,
                        code="BSL199",
                        message=(
                            'Синтаксическая конструкция вида "Если...Тогда...ИначеЕсли..." '
                            'должна содержать ветвь "Иначе".'
                        ),
                    )
                )
        i += 1
    return diags


def run_bsl255_try_number(path: str, lines: list[str]) -> list[Any]:
    _diag = _diag_module()
    diags: list[Any] = []
    re_try = re.compile(r"^\s*(?:Попытка|Try)\b", re.IGNORECASE)
    re_endtry = re.compile(r"^\s*(?:КонецПопытки|EndTry)\b", re.IGNORECASE)
    re_except = re.compile(r"^\s*(?:Исключение|Except)\b", re.IGNORECASE)
    re_number = re.compile(r"\b(?:Число|Number)\s*\(", re.IGNORECASE)
    in_try_body = False
    for idx, line in enumerate(lines):
        if re_try.match(line):
            in_try_body = True
        elif re_except.match(line) or re_endtry.match(line):
            in_try_body = False
        if in_try_body:
            m = re_number.search(line)
            if m:
                diags.append(
                    _diag.Diagnostic(
                        file=path,
                        line=idx + 1,
                        character=m.start(),
                        end_line=idx + 1,
                        end_character=m.end(),
                        severity=_diag.Severity.WARNING,
                        code="BSL255",
                        message="Не следует использовать исключения для приведения значения к типу",
                    )
                )
    return diags


def run_bsl263_useless_for_each(path: str, lines: list[str]) -> list[Any]:
    _diag = _diag_module()
    diags: list[Any] = []
    re_foreach = re.compile(
        r"^\s*(?:Для\s+Каждого|For\s+Each)\s+(\w+)\s+(?:Из|In)\b", re.IGNORECASE | re.UNICODE
    )
    re_end_loop = re.compile(r"^\s*(?:КонецЦикла|EndDo)\b", re.IGNORECASE)
    re_comment = re.compile(r"^\s*//")
    i = 0
    while i < len(lines):
        m = re_foreach.match(lines[i])
        if m:
            iter_var = m.group(1).casefold()
            body_lines: list[str] = []
            depth = 1
            j = i + 1
            while j < len(lines) and depth > 0:
                bl = lines[j]
                if re_foreach.match(bl):
                    depth += 1
                elif re_end_loop.match(bl):
                    depth -= 1
                if depth >= 1:
                    body_lines.append(bl)
                j += 1
            var_used = False
            for bl in body_lines:
                if re_comment.match(bl):
                    continue
                clean = re.sub(r'"[^"]*"', '""', bl)
                if re.search(r"\b" + re.escape(iter_var) + r"\b", clean, re.IGNORECASE):
                    var_used = True
                    break
            if not var_used and body_lines:
                diags.append(
                    _diag.Diagnostic(
                        file=path,
                        line=i + 1,
                        character=0,
                        end_line=i + 1,
                        end_character=len(lines[i]),
                        severity=_diag.Severity.WARNING,
                        code="BSL263",
                        message=f"Переменная «{m.group(1)}» в «Для Каждого» нигде не используется в теле цикла",
                    )
                )
        i += 1
    return diags


def run_bsl265_useless_ternary_operator(path: str, lines: list[str]) -> list[Any]:
    _diag = _diag_module()
    diags: list[Any] = []
    re_ternary = re.compile(
        r"\?\s*\([^,]+,\s*(?:Истина|True|Ложь|False)\s*,\s*(?:Истина|True|Ложь|False)\s*\)",
        re.IGNORECASE | re.UNICODE,
    )
    re_comment = re.compile(r"^\s*//")
    for idx, line in enumerate(lines):
        if re_comment.match(line):
            continue
        m = re_ternary.search(line)
        if m:
            diags.append(
                _diag.Diagnostic(
                    file=path,
                    line=idx + 1,
                    character=m.start(),
                    end_line=idx + 1,
                    end_character=m.end(),
                    severity=_diag.Severity.WARNING,
                    code="BSL265",
                    message="Тернарный оператор возвращает Истина/Ложь — замените на само условие",
                )
            )
    return diags
