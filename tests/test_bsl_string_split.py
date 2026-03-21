"""Unit tests for split_commas_outside_double_quotes."""

from __future__ import annotations

from onec_hbk_bsl.analysis.bsl_string_split import split_commas_outside_double_quotes


def test_comma_inside_default_string() -> None:
    s = 'Знач Строка, Разделитель = ",", ВключатьПустые = Истина'
    parts = split_commas_outside_double_quotes(s)
    assert len(parts) == 3
    assert parts[1].strip().startswith("Разделитель")


def test_empty_and_no_commas() -> None:
    assert split_commas_outside_double_quotes("") == []
    assert split_commas_outside_double_quotes("  ") == []
    assert split_commas_outside_double_quotes("А") == ["А"]


def test_doubled_quote_escape_inside_literal() -> None:
    """Inside a string, "" is one escaped quote — comma after stays inside."""
    s = r'П = "a""b,c"'
    parts = split_commas_outside_double_quotes(s)
    assert len(parts) == 1
