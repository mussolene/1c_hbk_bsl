"""Unit tests for split_commas_outside_double_quotes."""

from __future__ import annotations

from onec_hbk_bsl.analysis.bsl_string_split import (
    parameter_name_from_declaration_fragment,
    split_commas_outside_double_quotes,
    strip_leading_val_keywords,
)


def test_comma_inside_default_string() -> None:
    s = 'Знач Строка, Разделитель = ",", ВключатьПустые = Истина'
    parts = split_commas_outside_double_quotes(s)
    assert len(parts) == 3
    assert parts[1].strip().startswith("Разделитель")


def test_empty_and_no_commas() -> None:
    assert split_commas_outside_double_quotes("") == []
    assert split_commas_outside_double_quotes("  ") == []
    assert split_commas_outside_double_quotes("А") == ["А"]


def test_parameter_name_from_declaration_fragment() -> None:
    """Имя параметра: снятие Знач/Val, затем часть до «=» (значение по умолчанию может содержать «,» в кавычках)."""
    assert parameter_name_from_declaration_fragment("Знач Строка") == "Строка"
    assert parameter_name_from_declaration_fragment("Знач Знач Строка") == "Строка"
    assert parameter_name_from_declaration_fragment("Val Detail") == "Detail"
    assert parameter_name_from_declaration_fragment('Разделитель = ","') == "Разделитель"
    assert parameter_name_from_declaration_fragment("") == ""


def test_strip_leading_val_keywords_double_prefix() -> None:
    assert strip_leading_val_keywords("Знач Знач Строка") == "Строка"
    assert strip_leading_val_keywords("Val Val Name") == "Name"


def test_doubled_quote_escape_inside_literal() -> None:
    """Inside a string, "" is one escaped quote — comma after stays inside."""
    s = r'П = "a""b,c"'
    parts = split_commas_outside_double_quotes(s)
    assert len(parts) == 1
