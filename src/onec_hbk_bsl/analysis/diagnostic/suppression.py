from __future__ import annotations

from typing import Any

from onec_hbk_bsl.analysis.diagnostic.string_state import (
    build_line_string_states,
    comment_start_outside_double_quotes,
)

Suppressions = dict[int, set[str]]
BSLLS_OFF_FLAGS = frozenset({"off", "выкл"})
_ALL_DIAGNOSTICS = "<all>"


def parse_suppressions(lines: list[str]) -> Suppressions:
    from onec_hbk_bsl.analysis import diagnostics as _diag

    result: Suppressions = {}
    bslls_stacks: dict[str, list[int]] = {}
    inline_stacks: dict[tuple[str, str], list[int]] = {}
    ranges: list[tuple[str, int, int]] = []
    string_states = build_line_string_states(lines)

    for idx, line in enumerate(lines):
        line_no = idx + 1
        stripped = line.lstrip()
        if stripped.startswith("//"):
            comment_start = len(line) - len(stripped)
        else:
            comment_start = comment_start_outside_double_quotes(line, string_states[idx])
        if comment_start is None:
            continue
        comment = line[comment_start:]
        has_code_before_comment = bool(line[:comment_start].strip())

        opening_match = _diag._RE_NOQA.fullmatch(comment)
        if opening_match is not None:
            family = opening_match.group("marker").lower()
            keys = _suppression_keys(opening_match.group("codes"))
            if has_code_before_comment:
                _add_line_suppressions(result, line_no, keys)
            else:
                for key in keys:
                    inline_stacks.setdefault((family, key), []).append(line_no)
            continue

        closing_match = _diag._RE_INLINE_SUPPRESSION_ENABLE.fullmatch(comment)
        if closing_match is not None and not has_code_before_comment:
            family = {
                "noqa-enable": "noqa",
                "bsl-enable": "bsl-disable",
            }[closing_match.group("marker").lower()]
            for key in _suppression_keys(closing_match.group("codes")):
                stack = inline_stacks.get((family, key))
                if stack:
                    ranges.append((key, stack.pop(), line_no))
            continue

        bslls_match = _diag._RE_BSLLS.search(comment)
        if bslls_match is None:
            continue
        key = _bslls_suppression_key(_diag, bslls_match)
        if key is None:
            continue
        is_off = bslls_match.group("flag").lower() in BSLLS_OFF_FLAGS
        if is_off and has_code_before_comment:
            ranges.append((key, line_no, line_no))
            continue
        stack = bslls_stacks.setdefault(key, [])
        if is_off:
            stack.append(line_no)
        elif stack:
            start_line = stack.pop()
            ranges.append((key, start_line, line_no))

    last_token_line = _last_token_line(lines, string_states)
    for (_, key), stack in inline_stacks.items():
        for start_line in stack:
            ranges.append((key, start_line, last_token_line))
    for key, stack in bslls_stacks.items():
        for start_line in stack:
            ranges.append((key, start_line, last_token_line))

    for key, start_line, end_line in ranges:
        for line_no in range(max(1, start_line), max(start_line, end_line) + 1):
            if key == _ALL_DIAGNOSTICS:
                result[line_no] = set()
            elif line_no not in result:
                result.setdefault(line_no, set()).add(key)
            elif result[line_no]:
                result[line_no].add(key)

    return result


def _suppression_keys(codes: str | None) -> set[str]:
    if not codes:
        return {_ALL_DIAGNOSTICS}
    return {code.strip().upper() for code in codes.split(",") if code.strip()}


def _add_line_suppressions(result: Suppressions, line_no: int, keys: set[str]) -> None:
    if _ALL_DIAGNOSTICS in keys:
        result[line_no] = set()
    elif line_no not in result or result[line_no]:
        result.setdefault(line_no, set()).update(keys)


def _bslls_suppression_key(_diag: Any, match: Any) -> str | None:
    name = match.group("name")
    if name is None:
        return _ALL_DIAGNOSTICS
    return _diag._BSLLS_NAME_TO_CODE.get(name)


def _last_token_line(lines: list[str], string_states: list[bool]) -> int:
    last = 0
    for idx, line in enumerate(lines):
        comment_start = comment_start_outside_double_quotes(line, string_states[idx])
        code = line if comment_start is None else line[:comment_start]
        if code.strip() or comment_start is not None:
            last = idx + 1
    return last


def is_suppressed(diag: Any, suppressed: Suppressions) -> bool:
    codes = suppressed.get(diag.line)
    if codes is None:
        return False
    return len(codes) == 0 or diag.code.upper() in codes
