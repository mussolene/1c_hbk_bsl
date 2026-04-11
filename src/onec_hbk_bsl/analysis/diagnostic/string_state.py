from __future__ import annotations

import re

_RE_DOUBLE_QUOTED_STRING = re.compile(r'"[^"]*"')


def comment_start_outside_double_quotes(line: str, in_str_at_start: bool = False) -> int | None:
    in_str = in_str_at_start
    i = 0
    n = len(line)
    while i < n - 1:
        ch = line[i]
        if ch == '"':
            in_str = not in_str
            i += 1
            continue
        if not in_str and ch == "/" and line[i + 1] == "/":
            return i
        i += 1
    return None


def span_is_inside_double_quoted_string(
    line: str,
    start: int,
    end: int,
    *,
    in_str_at_start: bool = False,
) -> bool:
    in_str = in_str_at_start
    segment_start: int | None = 0 if in_str else None
    for idx, ch in enumerate(line):
        if ch != '"':
            continue
        if in_str:
            if segment_start is None:
                segment_start = 0
            if segment_start <= start and idx + 1 >= end:
                return True
            in_str = False
            segment_start = None
        else:
            in_str = True
            segment_start = idx
    if in_str and segment_start is not None and segment_start <= start:
        return True
    return False


def comma_missing_space_after_cols_in_line(line: str) -> list[int]:
    in_str = False
    i = 0
    n = len(line)
    cols: list[int] = []
    while i < n - 1:
        ch = line[i]
        if ch == '"':
            in_str = not in_str
            i += 1
            continue
        if in_str:
            i += 1
            continue
        if ch == ",":
            nxt = line[i + 1]
            if nxt not in " \t\n\r)]\n":
                cols.append(i)
        i += 1
    return cols


def mask_double_quoted_strings_preserve_len(line: str) -> str:
    return _RE_DOUBLE_QUOTED_STRING.sub(lambda m: '"' + (" " * (len(m.group(0)) - 2)) + '"', line)


def strip_inline_comment_preserve_strings(line: str) -> str:
    masked = mask_double_quoted_strings_preserve_len(line)
    comment_pos = masked.find("//")
    return line[:comment_pos] if comment_pos >= 0 else line


def build_line_string_states(lines: list[str]) -> list[bool]:
    states: list[bool] = []
    in_str = False
    for line in lines:
        states.append(in_str)
        i = 0
        while i < len(line):
            if line[i] == '"':
                in_str = not in_str
            i += 1
    return states
