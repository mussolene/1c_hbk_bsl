from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, fields
from pathlib import Path

import pytest

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


def test_semantic_fact_snapshot_is_immutable_revisioned_and_built_once(
    tmp_path: Path,
) -> None:
    from onec_hbk_bsl.analysis.semantic_facts import FactRevision

    content = """\
Процедура Тест() Экспорт
    Сообщить("ok");
    Запрос = "ВЫБРАТЬ 1";
КонецПроцедуры
"""
    path = str(tmp_path / "Module.bsl")
    snapshot = build_document_snapshot(path, content=content)
    revision = FactRevision.for_content(content, index=2, metadata=3, config=4)

    with ThreadPoolExecutor(max_workers=8) as pool:
        facts = list(pool.map(lambda _item: snapshot.semantic_facts(revision), range(16)))

    assert all(item is facts[0] for item in facts)
    assert snapshot.semantic_fact_build_count == 1
    assert facts[0].revision == revision
    assert facts[0].revision.content_sha256
    assert facts[0].symbols[0].span.path == path
    assert facts[0].calls[0].span.start_line == 1
    assert facts[0].queries[0].span.start_line == 2
    with pytest.raises(FrozenInstanceError):
        facts[0].symbols[0].name = "ИзменитьНельзя"  # type: ignore[misc]

    next_revision = FactRevision.for_content(content, index=3, metadata=3, config=4)
    assert snapshot.semantic_facts(next_revision) is not facts[0]
    assert snapshot.semantic_fact_build_count == 2


def test_semantic_query_facts_resolve_metadata_once_and_preserve_unknown(
    tmp_path: Path,
) -> None:
    from onec_hbk_bsl.analysis.semantic_facts import FactRevision

    content = """\
Процедура Тест()
    Запрос.Текст = "ВЫБРАТЬ
    |    Таблица.Ссылка
    |ИЗ Справочник.Известный КАК Таблица
    |ЛЕВОЕ СОЕДИНЕНИЕ Документ.Неизвестный КАК Связь
    |ПО Таблица.Ссылка = Связь.Ссылка";
КонецПроцедуры
"""
    snapshot = build_document_snapshot(str(tmp_path / "Module.bsl"), content=content)
    calls: list[tuple[str, str]] = []

    def resolve(kind: str, name: str) -> tuple[str, ...]:
        calls.append((kind, name))
        return (f"{kind}.{name}",) if name == "Известный" else ()

    revision = FactRevision.for_content(content, metadata=7)
    facts = snapshot.semantic_facts(revision, metadata_resolver=resolve)
    repeated = snapshot.semantic_facts(revision, metadata_resolver=resolve)

    assert repeated is facts
    assert snapshot.semantic_fact_build_count == 1
    assert calls == [
        ("Catalog", "Известный"),
        ("Document", "Неизвестный"),
    ]
    contexts = {(context.collection, context.name): context for context in facts.metadata_contexts}
    known = contexts[("Catalog", "Известный")]
    missing = contexts[("Document", "Неизвестный")]
    assert known.state == "resolved"
    assert known.candidate_names == ("Catalog.Известный",)
    assert known.catalog_available is True
    assert missing.state == "unknown"
    assert missing.candidate_names == ()
    assert missing.span.end_character > missing.span.start_character


def test_semantic_receiver_facts_preserve_resolution_and_exact_span(tmp_path: Path) -> None:
    from onec_hbk_bsl.analysis.semantic_facts import FactRevision

    content = (
        "Элемент = Справочники.Организации.СоздатьЭлемент();\n"
        "Элемент.Записать();\n"
        "Неясный.Выполнить();\n"
    )
    snapshot = build_document_snapshot(str(tmp_path / "Module.bsl"), content=content)

    def resolve(node: object, line0: int) -> tuple[str | None, str | list[str] | None]:
        text = node.text.decode("utf-8")  # type: ignore[attr-defined]
        if text == "Элемент":
            return "СправочникОбъект", "СправочникОбъект.Организации"
        if text == "Неясный":
            return "ДокументСсылка", ["ДокументСсылка.А", "ДокументСсылка.Б"]
        return None, None

    facts = snapshot.semantic_facts(
        FactRevision.for_content(content, metadata=9),
        receiver_resolver=resolve,
    )
    receivers = {receiver.expression: receiver for receiver in facts.receivers}

    resolved = receivers["Элемент"]
    assert resolved.state == "resolved"
    assert resolved.candidate_types == ("СправочникОбъект.Организации",)
    assert resolved.span.start_line == 1
    assert resolved.span.start_character == 0
    assert resolved.span.end_character == len("Элемент")

    ambiguous = receivers["Неясный"]
    assert ambiguous.state == "ambiguous"
    assert ambiguous.candidate_types == ("ДокументСсылка.А", "ДокументСсылка.Б")


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


def test_global_method_call_facts_are_reused_from_snapshot(tmp_path: Path) -> None:
    from onec_hbk_bsl.analysis.diagnostic.cst import iter_ts_nodes
    from onec_hbk_bsl.analysis.diagnostics import DiagnosticEngine

    content = 'Сообщить("Первый");\nСообщить("Второй");\n'
    snapshot = build_document_snapshot(str(tmp_path / "Module.bsl"), content=content)
    engine = DiagnosticEngine()
    nodes = snapshot.ts_nodes_for_types({"method_call"}, walker=iter_ts_nodes)["method_call"]

    first = engine._global_method_calls_from_nodes(nodes, snapshot.lines, snapshot=snapshot)
    second = engine._global_method_calls_from_nodes(nodes, snapshot.lines, snapshot=snapshot)

    assert len(first) == 2
    assert second is first
