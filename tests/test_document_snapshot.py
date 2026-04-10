from __future__ import annotations

from pathlib import Path

from onec_hbk_bsl.analysis.document_snapshot import build_document_snapshot


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
