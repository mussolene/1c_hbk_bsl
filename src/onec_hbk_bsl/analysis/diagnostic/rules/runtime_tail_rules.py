from __future__ import annotations

import re
from typing import Any


def _diag_module() -> Any:
    from onec_hbk_bsl.analysis import diagnostics as _diag

    return _diag


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
            is_nested_if = bool(_diag._RE_BSL197_IF.match(bl))
            is_endif = bool(_diag._RE_BSL197_ENDIF.match(bl))
            if is_nested_if:
                depth += 1
            elif is_endif:
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
                if depth >= 1:
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
