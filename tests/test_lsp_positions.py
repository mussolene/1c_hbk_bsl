"""Tests for UTF-8 byte column → LSP UTF-16 character mapping."""

from __future__ import annotations

from bsl_analyzer.analysis.lsp_positions import utf8_byte_offset_to_lsp_character, utf16_len


def test_utf8_byte_offset_cyrillic_function_header() -> None:
    line = "Функция ИННСертификата(СубъектСертификата)"
    byte_at_name = len("Функция ".encode())
    # 7 letters + space = 8 UTF-16 code units before identifier
    assert utf8_byte_offset_to_lsp_character(line, byte_at_name) == 8


def test_utf16_len_bmp_matches_python_len() -> None:
    assert utf16_len("ИННСертификата") == len("ИННСертификата")


def test_utf8_byte_offset_zero_and_empty() -> None:
    assert utf8_byte_offset_to_lsp_character("Функция X()", 0) == 0
    assert utf8_byte_offset_to_lsp_character("", 5) == 0
