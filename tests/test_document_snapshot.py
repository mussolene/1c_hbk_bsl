from __future__ import annotations

from dataclasses import fields
from pathlib import Path

from onec_hbk_bsl.analysis import document_snapshot as snapshot_mod
from onec_hbk_bsl.analysis.document_snapshot import (
    LineDiagnosticFact,
    build_document_snapshot,
    find_procedure_names_from_tree,
    find_procedure_names_in_content,
)
from onec_hbk_bsl.analysis.source_positions import line_start_offsets


def test_snapshot_collects_core_document_views(tmp_path: Path) -> None:
    content = """\
#Область ПрограммныйИнтерфейс
Процедура Тест(Знач П1, П2 = 1) Экспорт
    Сообщить(П1);
КонецПроцедуры
#КонецОбласти
"""
    snapshot = build_document_snapshot(
        str(tmp_path / "Module.bsl"),
        content=content,
    )

    assert snapshot.tree_ok
    assert snapshot.lines[1] == "Процедура Тест(Знач П1, П2 = 1) Экспорт"
    assert len(snapshot.procedures) == 1
    assert snapshot.procedures[0].name == "Тест"
    assert snapshot.procedures[0].val_params == ["П1"]
    assert snapshot.procedures[0].optional_params == frozenset({"П2"})
    assert len(snapshot.regions) == 1
    assert snapshot.regions[0].name == "ПрограммныйИнтерфейс"
    assert ("Тест", snapshot.procedures[0].start_idx, "procedure") in snapshot.proc_node_map
    assert any(call.callee_name == "Сообщить" for call in snapshot.calls)
    assert any(symbol.name == "Тест" and symbol.kind == "procedure" for symbol in snapshot.symbols)


def test_line_diagnostic_fact_has_no_user_message_payload() -> None:
    assert {field.name for field in fields(LineDiagnosticFact)} == {
        "line_idx",
        "character",
        "end_character",
        "end_line_idx",
    }


def test_cst_string_ranges_skip_line_comment() -> None:
    content = '// "fake" string\nА = 1;\n'
    snapshot = build_document_snapshot("<test>", content=content)
    assert snapshot.string_literal_ranges == ()


def test_cst_string_ranges_include_multiline_literal() -> None:
    content = 'П = "строка\n|Если внутри\n|конец";\n'
    snapshot = build_document_snapshot("<test>", content=content)
    ranges = snapshot.string_literal_ranges
    assert len(ranges) == 1
    start, end = ranges[0]
    assert content[start] == '"'
    assert content[end - 1] == '"'


def test_credential_single_string_expression_uses_structural_shape(
    monkeypatch,
    tmp_path: Path,
) -> None:
    content = 'Пароль = "secret";\nДругойПароль = ("secret");\n'
    snapshot = build_document_snapshot(str(tmp_path / "Module.bsl"), content=content)
    assignments = snapshot.ts_nodes_for_types(
        {"assignment_statement"}, walker=snapshot_mod._ts_walk
    )["assignment_statement"]
    _left, direct_value = snapshot_mod._credential_assignment_parts(assignments[0])
    _left, parenthesized_value = snapshot_mod._credential_assignment_parts(assignments[1])

    monkeypatch.setattr(
        snapshot_mod,
        "_ts_walk",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected walk")),
    )

    assert snapshot_mod._credential_single_string_expression(direct_value) is not None
    assert snapshot_mod._credential_single_string_expression(parenthesized_value) is None


def test_line_start_offsets() -> None:
    assert line_start_offsets("А\nБ\n") == [0, 2, 4]


def test_non_tree_sitter_snapshot_does_not_build_procedure_model(tmp_path: Path) -> None:
    content = """\
#Область Test
Функция Имя(Парам = 1)
    Возврат Парам;
КонецФункции
#КонецОбласти
"""
    snapshot = build_document_snapshot(
        str(tmp_path / "Module.bsl"),
        content=content,
        tree=object(),
    )

    assert snapshot.procedures == []
    assert snapshot.regions == []


def test_snapshot_collects_embedded_query_blocks(tmp_path: Path) -> None:
    content = """\
Процедура Тест()
    Запрос.Текст =
    "ВЫБРАТЬ
    |    Поле
    |ИЗ Справочник.Номенклатура // comment
    |ГДЕ Поле ПОДОБНО \"Тест%\"";
КонецПроцедуры
"""
    snapshot = build_document_snapshot(str(tmp_path / "Module.bsl"), content=content)

    assert len(snapshot.query_text_blocks) == 1
    block = snapshot.query_text_blocks[0]
    assert block.start_idx == 2
    assert "ВЫБРАТЬ" in block.query_text
    assert len(block.content_lines) == 4
    assert block.content_lines[0].line_no == 3
    assert block.content_lines[1].head == "Поле"
    assert block.content_lines[2].head == "ИЗ Справочник.Номенклатура"
    assert block.content_line_tuples[1] == (4, 9, "Поле", "Поле", False)
    assert snapshot.query_line_indices == frozenset({2, 3, 4, 5})
    assert snapshot.query_content_line_tuples is snapshot.query_content_line_tuples
    assert snapshot.query_content_line_tuples[2][3] == "ИЗ Справочник.Номенклатура"


def test_snapshot_collects_query_after_opening_quote_comments(tmp_path: Path) -> None:
    content = """\
Процедура Тест()
    Результат = "
    // Комментарий перед текстом запроса
    |ВЫБРАТЬ
    |    Таблица.Ссылка.Код КАК Код
    |ИЗ Справочник.Номенклатура КАК Таблица";
КонецПроцедуры
"""
    snapshot = build_document_snapshot(str(tmp_path / "Module.bsl"), content=content)

    assert len(snapshot.query_text_blocks) == 1
    assert [line.line_no for line in snapshot.query_text_blocks[0].content_lines] == [4, 5, 6]


def test_snapshot_ignores_fully_commented_query_blocks(tmp_path: Path) -> None:
    content = """\
Процедура Тест()
    // Запрос = Новый Запрос(
    // "ВЫБРАТЬ
    // |    Таблица.Ссылка.Код КАК Код
    // |ИЗ Справочник.Номенклатура КАК Таблица"
    // );
КонецПроцедуры
"""
    snapshot = build_document_snapshot(str(tmp_path / "Module.bsl"), content=content)

    assert snapshot.query_text_blocks == []


def test_procedure_name_extractors_handle_async_declarations(tmp_path: Path) -> None:
    content = """\
Асинх Функция ПолучитьАсинх(Парам = Неопределено) Экспорт
    Возврат Парам;
КонецФункции

Асинх Процедура ЗаписатьАсинх()
КонецПроцедуры
"""
    snapshot = build_document_snapshot(str(tmp_path / "Module.bsl"), content=content)

    assert find_procedure_names_from_tree(snapshot.tree) == frozenset(
        {"получитьасинх", "записатьасинх"}
    )
    assert find_procedure_names_in_content(content) == frozenset({"получитьасинх", "записатьасинх"})


def test_non_tree_sitter_snapshot_skips_async_procedure_model(tmp_path: Path) -> None:
    content = """\
Асинх Функция ВерсияАсинх() Экспорт
    Возврат 1;
КонецФункции
"""
    snapshot = build_document_snapshot(str(tmp_path / "Module.bsl"), content=content, tree=object())

    assert snapshot.procedures == []


def test_regions_require_tree_sitter_snapshot(tmp_path: Path) -> None:
    content = """\
#Область Outer
Процедура Тест()
#Область Inner
Сообщить("x");
#КонецОбласти
КонецПроцедуры
#КонецОбласти
"""
    snapshot = build_document_snapshot(str(tmp_path / "Module.bsl"), content=content, tree=object())

    assert snapshot.regions == []
