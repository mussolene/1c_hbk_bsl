from __future__ import annotations

from typing import Any

from onec_hbk_bsl.analysis.diagnostic.domain.method_doc_comment import (
    build_method_doc_comment,
)
from onec_hbk_bsl.analysis.document_snapshot import build_document_snapshot


def _walk(node: Any):
    yield node
    for child in getattr(node, "children", ()):
        yield from _walk(child)


def test_builds_structured_doc_comment_from_cst_comments() -> None:
    content = """\
// Описание метода.
//
// Параметры:
//  Первый - Строка - описание
//  Второй - Число - описание
Функция Пример(Первый, Второй)
КонецФункции
"""
    snapshot = build_document_snapshot("<test>", content=content)
    comment_nodes = snapshot.ts_nodes_for_types({"line_comment"}, walker=_walk)["line_comment"]

    doc = build_method_doc_comment(
        snapshot.lines,
        snapshot.procedures[0],
        line_comment_nodes=comment_nodes,
    )

    assert doc is not None
    assert doc.has_method_documentation
    assert doc.has_params_section
    assert doc.documented_names == ("Первый", "Второй")
    assert doc.empty_description_names == frozenset()


def test_ignores_non_method_structure_composition_block() -> None:
    content = """\
// Состав структуры:
//   Поле - Строка - значение
Функция Пример(Параметр)
КонецФункции
"""
    snapshot = build_document_snapshot("<test>", content=content)

    doc = build_method_doc_comment(snapshot.lines, snapshot.procedures[0])

    assert doc is not None
    assert not doc.has_method_documentation


def test_inline_comment_before_method_is_not_doc_block() -> None:
    content = """\
Значение = 1; // не описание метода
Функция Пример(Параметр)
КонецФункции
"""
    snapshot = build_document_snapshot("<test>", content=content)
    comment_nodes = snapshot.ts_nodes_for_types({"line_comment"}, walker=_walk)["line_comment"]

    doc = build_method_doc_comment(
        snapshot.lines,
        snapshot.procedures[0],
        line_comment_nodes=comment_nodes,
    )

    assert doc is None
