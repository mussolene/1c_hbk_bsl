"""Tests for tree-sitter structural indent (formatter_structural)."""
from __future__ import annotations

from onec_hbk_bsl.analysis.formatter_structural import ast_structural_indent_levels, tree_has_errors
from onec_hbk_bsl.parser.bsl_parser import BslParser


def test_ast_indent_procedure_and_if() -> None:
    code = """Процедура Тест()
Если А Тогда
Б = 1;
КонецЕсли;
КонецПроцедуры
"""
    p = BslParser()
    tree = p.parse_content(code)
    assert getattr(tree, "content", None) is None
    assert not tree_has_errors(tree.root_node)
    lines = code.splitlines()
    levels = ast_structural_indent_levels(tree.root_node, len(lines))
    assert levels[0] == 0  # Процедура
    assert levels[1] == 1  # Если
    assert levels[2] == 2  # Б = 1
    assert levels[3] == 1  # КонецЕсли
    assert levels[4] == 0  # КонецПроцедуры
