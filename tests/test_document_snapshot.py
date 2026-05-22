from __future__ import annotations

from pathlib import Path

from onec_hbk_bsl.analysis.document_snapshot import (
    build_document_snapshot,
    find_procedure_names_from_tree,
    find_procedure_names_in_content,
)


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


def test_snapshot_falls_back_to_regex_views_when_tree_is_not_real_ts(tmp_path: Path) -> None:
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

    assert snapshot.procedures[0].name == "Имя"
    assert snapshot.regions[0].name == "Test"


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


def test_regex_fallback_snapshot_collects_async_procedures(tmp_path: Path) -> None:
    content = """\
Асинх Функция ВерсияАсинх() Экспорт
    Возврат 1;
КонецФункции
"""
    snapshot = build_document_snapshot(str(tmp_path / "Module.bsl"), content=content, tree=object())

    assert [proc.name for proc in snapshot.procedures] == ["ВерсияАсинх"]


def test_regex_fallback_regions_match_nested_blocks(tmp_path: Path) -> None:
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

    assert [(region.name, region.start_idx, region.end_idx) for region in snapshot.regions] == [
        ("Outer", 0, 6),
        ("Inner", 2, 4),
    ]
