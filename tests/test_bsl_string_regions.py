"""Tests for string-literal range detection (diagnostic suppression)."""

from __future__ import annotations

from onec_hbk_bsl.analysis.bsl_string_regions import (
    diagnostic_overlaps_string_literal,
    double_quoted_string_ranges,
    line_start_offsets,
)


def test_double_quoted_ranges_skip_line_comment() -> None:
    content = '// "fake" string\nА = 1;\n'
    ranges = double_quoted_string_ranges(content)
    assert ranges == []


def test_double_quoted_multiline_literal() -> None:
    content = 'П = "строка\n|Если внутри\n|конец";\n'
    ranges = double_quoted_string_ranges(content)
    assert len(ranges) == 1
    start, end = ranges[0]
    assert content[start] == '"'
    assert content[end - 1] == '"'


def test_diagnostic_overlaps_inside_string() -> None:
    content = 'Сообщить("Процедура плохо()");\n'
    r = double_quoted_string_ranges(content)
    # Overlap with substring inside quotes
    assert diagnostic_overlaps_string_literal(
        content,
        line=1,
        character=content.index("Процедура"),
        end_line=1,
        end_character=content.index("Процедура") + len("Процедура"),
        ranges=r,
    )


def test_diagnostic_outside_string() -> None:
    content = 'Процедура Т()\nКонецПроцедуры\n'
    r = double_quoted_string_ranges(content)
    assert not diagnostic_overlaps_string_literal(
        content,
        line=1,
        character=0,
        end_line=1,
        end_character=len("Процедура"),
        ranges=r,
    )


def test_diagnostic_overlap_with_line_starts_matches_without() -> None:
    """Precomputed line table must match the default path (used in _run_rules)."""
    content = 'Сообщить("Процедура плохо()");\n'
    r = double_quoted_string_ranges(content)
    ls = line_start_offsets(content)
    args = dict(
        content=content,
        line=1,
        character=content.index("Процедура"),
        end_line=1,
        end_character=content.index("Процедура") + len("Процедура"),
        ranges=r,
    )
    a = diagnostic_overlaps_string_literal(**args)
    b = diagnostic_overlaps_string_literal(**args, line_starts=ls)
    assert a == b
