"""BSL148 AllFunctionPathMustHaveReturn — BSLLS fixture parity (default loop option)."""

from __future__ import annotations

from pathlib import Path

import pytest

from onec_hbk_bsl.analysis.diagnostics import DiagnosticEngine, Severity

_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "diag_bslls"
    / "AllFunctionPathMustHaveReturnDiagnostic.bsl"
)


@pytest.mark.skipif(not _FIXTURE.is_file(), reason="copy from BSLLS diagnostics resources")
def test_bsl148_matches_bslls_default_fixture() -> None:
    engine = DiagnosticEngine(select={"BSL148"})
    diags = [d for d in engine.check_file(str(_FIXTURE)) if d.code == "BSL148"]
    lines = sorted({d.line for d in diags})
    assert lines == [1, 26, 94, 103, 132]


@pytest.mark.skipif(not _FIXTURE.is_file(), reason="copy from BSLLS diagnostics resources")
def test_bsl148_loops_false_adds_for_loop_case() -> None:
    engine = DiagnosticEngine(
        select={"BSL148"},
        bsl148_loops_executed_at_least_once=False,
    )
    diags = [d for d in engine.check_file(str(_FIXTURE)) if d.code == "BSL148"]
    lines = sorted({d.line for d in diags})
    assert lines == [1, 26, 37, 94, 103, 132]


def test_bsl148_ignores_return_in_nested_routine(tmp_path: Path) -> None:
    content = (
        "Функция Внешняя()\n"
        "    Функция Внутренняя()\n"
        "        Возврат Истина;\n"
        "    КонецФункции\n"
        "КонецФункции\n"
    )
    path = tmp_path / "nested_return.bsl"
    path.write_text(content, encoding="utf-8")
    engine = DiagnosticEngine(select={"BSL148"})
    diags = [d for d in engine.check_file(str(path)) if d.code == "BSL148"]
    assert diags == []


def test_bsl148_nested_if_with_total_returns_is_not_reported(tmp_path: Path) -> None:
    content = (
        "Функция Внешняя(Флаг)\n"
        "    Если Флаг Тогда\n"
        "        Если Истина Тогда\n"
        "            Возврат 1;\n"
        "        Иначе\n"
        "            Возврат 2;\n"
        "        КонецЕсли;\n"
        "    Иначе\n"
        "        Возврат 3;\n"
        "    КонецЕсли;\n"
        "КонецФункции\n"
    )
    path = tmp_path / "nested_if_total_returns.bsl"
    path.write_text(content, encoding="utf-8")
    diags = [
        d for d in DiagnosticEngine(select={"BSL148"}).check_file(str(path)) if d.code == "BSL148"
    ]
    assert diags == []


def test_bsl148_anchor_points_to_function_identifier(tmp_path: Path) -> None:
    content = (
        "Функция Тест(Флаг)\n"
        "    Если Флаг Тогда\n"
        "        Возврат 1;\n"
        "    ИначеЕсли Не Флаг Тогда\n"
        "        Возврат 0;\n"
        "    КонецЕсли;\n"
        "КонецФункции\n"
    )
    path = tmp_path / "anchor_identifier.bsl"
    path.write_text(content, encoding="utf-8")
    diags = [
        d for d in DiagnosticEngine(select={"BSL148"}).check_file(str(path)) if d.code == "BSL148"
    ]
    assert len(diags) == 1
    assert diags[0].line == 1
    assert diags[0].character == 8
    assert diags[0].end_character > diags[0].character
    assert diags[0].severity == Severity.ERROR


def test_bsl148_simple_trailing_if_without_else_is_not_reported(tmp_path: Path) -> None:
    content = (
        "Функция Тест(Флаг)\n"
        "    Если Флаг Тогда\n"
        "        Возврат 1;\n"
        "    КонецЕсли;\n"
        "КонецФункции\n"
    )
    path = tmp_path / "simple_trailing_if.bsl"
    path.write_text(content, encoding="utf-8")
    diags = [
        d for d in DiagnosticEngine(select={"BSL148"}).check_file(str(path)) if d.code == "BSL148"
    ]
    assert diags == []


def test_bsl148_try_except_with_guaranteed_returns_is_not_reported(tmp_path: Path) -> None:
    content = (
        "Функция Тест(Флаг)\n"
        "    Попытка\n"
        "        Если Флаг Тогда\n"
        "            Возврат 1;\n"
        "        Иначе\n"
        "            Возврат 2;\n"
        "        КонецЕсли;\n"
        "    Исключение\n"
        "        Возврат 0;\n"
        "    КонецПопытки;\n"
        "КонецФункции\n"
    )
    path = tmp_path / "try_except_returns.bsl"
    path.write_text(content, encoding="utf-8")
    diags = [
        d for d in DiagnosticEngine(select={"BSL148"}).check_file(str(path)) if d.code == "BSL148"
    ]
    assert diags == []


def test_bsl148_try_except_missing_except_return_is_reported(tmp_path: Path) -> None:
    content = (
        "Функция Тест()\n"
        "    Попытка\n"
        "        Возврат 1;\n"
        "    Исключение\n"
        "        Сообщить(ОписаниеОшибки());\n"
        "    КонецПопытки;\n"
        "КонецФункции\n"
    )
    path = tmp_path / "try_except_missing_except_return.bsl"
    path.write_text(content, encoding="utf-8")
    diags = [
        d for d in DiagnosticEngine(select={"BSL148"}).check_file(str(path)) if d.code == "BSL148"
    ]
    assert [d.line for d in diags] == [1]


def test_bsl148_try_except_followed_by_return_is_not_reported(tmp_path: Path) -> None:
    content = (
        "Функция Тест()\n"
        "    Попытка\n"
        "        Значение = ПолучитьЗначение();\n"
        "    Исключение\n"
        "        ВызватьИсключение;\n"
        "    КонецПопытки;\n"
        "    Возврат Значение;\n"
        "КонецФункции\n"
    )
    path = tmp_path / "try_except_then_return.bsl"
    path.write_text(content, encoding="utf-8")
    diags = [
        d for d in DiagnosticEngine(select={"BSL148"}).check_file(str(path)) if d.code == "BSL148"
    ]
    assert diags == []


def test_bsl148_branch_with_statements_before_return_is_not_reported(tmp_path: Path) -> None:
    content = (
        "Функция Тест(Флаг)\n"
        "    Если Флаг Тогда\n"
        "        Значение = 1;\n"
        "        Подготовить(Значение);\n"
        "        Возврат Значение;\n"
        "    Иначе\n"
        "        Возврат 0;\n"
        "    КонецЕсли;\n"
        "КонецФункции\n"
    )
    path = tmp_path / "branch_statements_before_return.bsl"
    path.write_text(content, encoding="utf-8")
    diags = [
        d for d in DiagnosticEngine(select={"BSL148"}).check_file(str(path)) if d.code == "BSL148"
    ]
    assert diags == []


def test_bsl148_branch_with_comments_before_return_is_not_reported(tmp_path: Path) -> None:
    content = (
        "Функция Тест(Флаг)\n"
        "    Если Флаг Тогда\n"
        "        // пояснение перед возвратом\n"
        "        Возврат 1;\n"
        "    Иначе\n"
        "        Возврат 0;\n"
        "    КонецЕсли;\n"
        "КонецФункции\n"
    )
    path = tmp_path / "branch_comments_before_return.bsl"
    path.write_text(content, encoding="utf-8")
    diags = [
        d for d in DiagnosticEngine(select={"BSL148"}).check_file(str(path)) if d.code == "BSL148"
    ]
    assert diags == []


def test_bsl148_terminal_loop_branch_reports_when_body_can_continue(
    tmp_path: Path,
) -> None:
    content = (
        "Функция Найти(Коллекция, Поиск)\n"
        '    Если ТипЗнч(Поиск) = Тип("Число") Тогда\n'
        "        Возврат Неопределено;\n"
        "    Иначе\n"
        "        Для Каждого Элемент Из Коллекция Цикл\n"
        "            Если Элемент = Поиск Тогда\n"
        "                Возврат Элемент;\n"
        "            КонецЕсли;\n"
        "        КонецЦикла;\n"
        "    КонецЕсли;\n"
        "КонецФункции\n"
    )
    path = tmp_path / "terminal_loop_branch_default.bsl"
    path.write_text(content, encoding="utf-8")
    diags = [
        d for d in DiagnosticEngine(select={"BSL148"}).check_file(str(path)) if d.code == "BSL148"
    ]
    assert [d.line for d in diags] == [1]


def test_bsl148_terminal_loop_branch_can_report_when_loop_assumption_is_disabled(
    tmp_path: Path,
) -> None:
    content = (
        "Функция Найти(Коллекция, Поиск)\n"
        '    Если ТипЗнч(Поиск) = Тип("Число") Тогда\n'
        "        Возврат Неопределено;\n"
        "    Иначе\n"
        "        Для Каждого Элемент Из Коллекция Цикл\n"
        "            Если Элемент = Поиск Тогда\n"
        "                Возврат Элемент;\n"
        "            КонецЕсли;\n"
        "        КонецЦикла;\n"
        "    КонецЕсли;\n"
        "КонецФункции\n"
    )
    path = tmp_path / "terminal_loop_branch_strict.bsl"
    path.write_text(content, encoding="utf-8")
    engine = DiagnosticEngine(
        select={"BSL148"},
        bsl148_loops_executed_at_least_once=False,
    )
    diags = [d for d in engine.check_file(str(path)) if d.code == "BSL148"]
    assert [d.line for d in diags] == [1]


def test_bsl148_terminal_loop_with_guaranteed_body_return_is_not_reported(
    tmp_path: Path,
) -> None:
    content = (
        "Функция Первый(Коллекция)\n"
        "    Для Каждого Элемент Из Коллекция Цикл\n"
        "        Возврат Элемент;\n"
        "    КонецЦикла;\n"
        "КонецФункции\n"
    )
    path = tmp_path / "terminal_loop_body_returns.bsl"
    path.write_text(content, encoding="utf-8")
    diags = [
        d for d in DiagnosticEngine(select={"BSL148"}).check_file(str(path)) if d.code == "BSL148"
    ]
    assert diags == []


def test_bsl148_preprocessor_branches_with_total_returns_are_not_reported(
    tmp_path: Path,
) -> None:
    content = (
        "Функция ТестВсеПутиСВозвратом()\n"
        "    Если Условие1 Тогда\n"
        "        #Если Сервер Тогда\n"
        "            Если Условие2 Тогда\n"
        "                Возврат 1;\n"
        "            Иначе\n"
        "                Возврат 2;\n"
        "            КонецЕсли;\n"
        "        #Иначе\n"
        "            Возврат 4;\n"
        "        #КонецЕсли\n"
        "    Иначе\n"
        "        Возврат 5;\n"
        "    КонецЕсли;\n"
        "КонецФункции\n"
    )
    path = tmp_path / "preprocessor_all_paths_return.bsl"
    path.write_text(content, encoding="utf-8")
    diags = [
        d for d in DiagnosticEngine(select={"BSL148"}).check_file(str(path)) if d.code == "BSL148"
    ]
    assert diags == []


def test_bsl148_loop_followed_by_return_is_not_reported_when_loop_can_be_skipped(
    tmp_path: Path,
) -> None:
    content = (
        "Функция ПроверкаПрерыванийИПродолжений()\n"
        "    Пока Выборка.Следующий() Цикл\n"
        "        Если РезультатыОтбора.Количество() >= МаксКоличествоВыбранных Тогда\n"
        "            Прервать;\n"
        "        КонецЕсли;\n"
        "    КонецЦикла;\n"
        "    Возврат 1;\n"
        "КонецФункции\n"
    )
    path = tmp_path / "loop_then_return_strict.bsl"
    path.write_text(content, encoding="utf-8")
    engine = DiagnosticEngine(
        select={"BSL148"},
        bsl148_loops_executed_at_least_once=False,
    )
    diags = [d for d in engine.check_file(str(path)) if d.code == "BSL148"]
    assert diags == []
