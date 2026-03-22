"""AST-driven argument list spacing (formatter_ast_spacing)."""

from __future__ import annotations

from onec_hbk_bsl.analysis.formatter_ast_spacing import normalize_argument_list_spacing
from onec_hbk_bsl.parser.bsl_parser import BslParser


def test_normalize_argument_list_spacing_commas() -> None:
    src = "А = Метод( 1  ,2 , 3 );\n"
    p = BslParser()
    tree = p.parse_content(src)
    if getattr(tree, "content", None) is not None:
        return
    out = normalize_argument_list_spacing(src, tree.root_node)
    assert "Метод(1, 2, 3)" in out


def test_nested_calls_disjoint_spans() -> None:
    src = "А = Внеш( Внутр( 1 , 2 ) , 3 );\n"
    p = BslParser()
    tree = p.parse_content(src)
    if getattr(tree, "content", None) is not None:
        return
    out = normalize_argument_list_spacing(src, tree.root_node)
    assert "Внутр(1, 2)" in out
    assert "Внеш(" in out
