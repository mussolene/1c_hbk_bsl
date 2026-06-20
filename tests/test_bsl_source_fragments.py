"""Tests for BSL source-fragment helpers and CST string ranges."""

from __future__ import annotations

from onec_hbk_bsl.analysis.bsl_source_fragments import (
    parameter_name_from_declaration_fragment,
    split_commas_outside_double_quotes,
    strip_leading_val_keywords,
)
from onec_hbk_bsl.analysis.document_snapshot import DocumentSnapshot
from onec_hbk_bsl.analysis.source_positions import line_start_offsets
from onec_hbk_bsl.parser.bsl_parser import BslParser


def _snapshot(content: str) -> DocumentSnapshot:
    return DocumentSnapshot("<test>", content, BslParser().parse_content(content))


def test_cst_string_ranges_skip_line_comment() -> None:
    content = '// "fake" string\nА = 1;\n'
    assert _snapshot(content).string_literal_ranges == ()


def test_cst_string_ranges_include_multiline_literal() -> None:
    content = 'П = "строка\n|Если внутри\n|конец";\n'
    ranges = _snapshot(content).string_literal_ranges
    assert len(ranges) == 1
    start, end = ranges[0]
    assert content[start] == '"'
    assert content[end - 1] == '"'


def test_line_start_offsets() -> None:
    assert line_start_offsets("А\nБ\n") == [0, 2, 4]


def test_comma_inside_default_string() -> None:
    segment = 'Знач Строка, Разделитель = ",", ВключатьПустые = Истина'
    parts = split_commas_outside_double_quotes(segment)
    assert len(parts) == 3
    assert parts[1].strip().startswith("Разделитель")


def test_empty_and_no_commas() -> None:
    assert split_commas_outside_double_quotes("") == []
    assert split_commas_outside_double_quotes("  ") == []
    assert split_commas_outside_double_quotes("А") == ["А"]


def test_parameter_name_from_declaration_fragment() -> None:
    assert parameter_name_from_declaration_fragment("Знач Строка") == "Строка"
    assert parameter_name_from_declaration_fragment("Знач Знач Строка") == "Строка"
    assert parameter_name_from_declaration_fragment("Val Detail") == "Detail"
    assert parameter_name_from_declaration_fragment('Разделитель = ","') == "Разделитель"
    assert parameter_name_from_declaration_fragment("") == ""


def test_strip_leading_val_keywords_double_prefix() -> None:
    assert strip_leading_val_keywords("Знач Знач Строка") == "Строка"
    assert strip_leading_val_keywords("Val Val Name") == "Name"


def test_doubled_quote_escape_inside_literal() -> None:
    segment = r'П = "a""b,c"'
    assert split_commas_outside_double_quotes(segment) == [segment]
