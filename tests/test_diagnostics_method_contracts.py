"""Method and procedure contract diagnostics."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from onec_hbk_bsl.analysis.diagnostics import (
    Diagnostic,
    DiagnosticEngine,
    Severity,
)
from onec_hbk_bsl.indexer.incremental import IncrementalIndexer
from onec_hbk_bsl.indexer.symbol_index import SymbolIndex
from tests.diagnostic_test_support import _check, _codes, _rule_msg

pytestmark = pytest.mark.integration


# BSL192 — TestBsl192FunctionNameStartsWithGet
class TestBsl192FunctionNameStartsWithGet:
    def test_function_name_starts_with_get_russian_reports(self, tmp_path: Path) -> None:
        content = """\
            Функция ПолучитьДанные()
                Возврат 1;
            КонецФункции
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL192"}) if d.code == "BSL192"]
        assert len(diags) == 1
        assert diags[0].line == 1
        assert diags[0].character == 8
        assert diags[0].message == _rule_msg("BSL192")

    def test_function_name_starts_with_get_english_is_not_reported(self, tmp_path: Path) -> None:
        content = """\
            Function GetData()
                Return 1;
            EndFunction
        """
        diags = _check(content, tmp_path, select={"BSL192"})
        assert "BSL192" not in _codes(diags)

    def test_procedure_name_starts_with_get_russian_is_not_reported(self, tmp_path: Path) -> None:
        content = """\
            Процедура ПолучитьДанные()
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL192"})
        assert "BSL192" not in _codes(diags)


# BSL193 — TestBsl193FunctionOutParameter
class TestBsl193FunctionOutParameter:
    def test_function_out_parameter_assignment_reports(self, tmp_path: Path) -> None:
        content = """\
            Функция Тест(Параметр)
                Параметр = 1;
                Возврат Параметр;
            КонецФункции
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL193"}) if d.code == "BSL193"]
        assert len(diags) == 1
        assert diags[0].line == 2
        assert diags[0].character == 4

    def test_function_val_parameter_assignment_is_not_reported(self, tmp_path: Path) -> None:
        content = """\
            Функция Тест(Знач Параметр)
                Параметр = 1;
                Возврат Параметр;
            КонецФункции
        """
        diags = _check(content, tmp_path, select={"BSL193"})
        assert "BSL193" not in _codes(diags)

    def test_multiline_signature_default_is_not_assignment(self, tmp_path: Path) -> None:
        content = """\
            Функция Тест(Первый = Неопределено,
                Второй = Неопределено)
                Возврат Второй;
            КонецФункции
        """
        diags = _check(content, tmp_path, select={"BSL193"})
        assert "BSL193" not in _codes(diags)


# BSL212 — TestBsl212MissedRequiredParameter
class TestBsl212MissedRequiredParameter:
    def test_local_call_missing_required_parameter_reports(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Обработать();
            КонецПроцедуры

            Процедура Обработать(Параметр)
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL212"}) if d.code == "BSL212"]
        assert len(diags) == 1
        assert diags[0].message == "Укажите обязательный параметр Параметр"

    def test_qualified_call_does_not_resolve_to_local_method(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест(Модуль)
                Модуль.Обработать();
            КонецПроцедуры

            Процедура Обработать(Параметр)
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL212"})
        assert "BSL212" not in _codes(diags)

    def test_omitted_middle_required_parameter_reports(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Обработать(Первый, , Третий);
            КонецПроцедуры

            Процедура Обработать(Первый, Второй, Третий)
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL212"}) if d.code == "BSL212"]
        assert len(diags) == 1

    def test_call_range_excludes_statement_semicolon(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Обработать();
            КонецПроцедуры

            Процедура Обработать(Параметр)
            КонецПроцедуры
        """
        diag = [d for d in _check(content, tmp_path, select={"BSL212"}) if d.code == "BSL212"][0]
        assert diag.character == 4
        assert diag.end_character == 16

    def test_call_range_may_include_string_arguments(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Обработать(, "Имя", Значение);
            КонецПроцедуры

            Процедура Обработать(Первый, Второй, Третий)
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL212"}) if d.code == "BSL212"]
        assert len(diags) == 1


# BSL215 — TestBsl215MissingParameterDescriptionParity
class TestBsl215MissingParameterDescriptionParity:
    def test_service_comment_still_requires_parameter_descriptions(self, tmp_path: Path) -> None:
        content = """\
            // Служебная процедура
            Процедура Обработать(Параметр)
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL215"})
        assert "BSL215" in _codes(diags)

    def test_formal_doc_without_params_section_reports_method(self, tmp_path: Path) -> None:
        content = """\
            // Описание метода.
            //
            Процедура Обработать(Параметр)
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL215"})
        assert "BSL215" in _codes(diags)

    def test_blank_line_breaks_method_description(self, tmp_path: Path) -> None:
        content = """\
            // XML: служебные методы

            Процедура Обработать(Параметр)
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL215"})
        assert "BSL215" not in _codes(diags)

    def test_missing_single_param_message_matches_bslls_style(self, tmp_path: Path) -> None:
        content = """\
            // Описание метода.
            // Параметры:
            //   Имя - описание
            Функция Обработать(Имя, Стр)
            КонецФункции
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL215"}) if d.code == "BSL215"]
        assert len(diags) == 1
        assert all(d.message == _rule_msg("BSL215") for d in diags)

    def test_documented_params_without_signature_params_are_stale(self, tmp_path: Path) -> None:
        content = """\
            // Описание метода.
            // Параметры:
            // Параметр1 - Строка - описание
            // Параметр2 - Строка - описание
            Функция Пример()
            КонецФункции
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL215"}) if d.code == "BSL215"]
        assert not diags

    def test_documented_param_order_matches_bslls(self, tmp_path: Path) -> None:
        content = """\
            // Описание метода.
            // Параметры:
            // Параметр2 - Строка - описание
            // Параметр1 - Строка - описание
            Функция Пример(Параметр1, Параметр2)
            КонецФункции
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL215"}) if d.code == "BSL215"]
        assert len(diags) == 1
        assert diags[0].message == _rule_msg("BSL215")

    def test_param_with_multiple_types_is_documented(self, tmp_path: Path) -> None:
        content = """\
            // Описание метода.
            // Параметры:
            //  ДокументОплаты - ДокументСсылка.СписаниеСРасчетногоСчета, ДокументСсылка.ПлатежноеПоручение
            //        - документ оплаты.
            Функция Пример(ДокументОплаты)
            КонецФункции
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL215"}) if d.code == "BSL215"]
        assert diags == []

    def test_struct_param_with_fields_is_documented(self, tmp_path: Path) -> None:
        content = """\
            // Описание метода.
            // Параметры:
            //  ДополнительныеСвойства - Структура - Дополнительные свойства:
            //   * ТаблицыДляДвижений - Структура - таблицы для движений
            //  Движения - КоллекцияДвижений - Движения документа
            //  Отказ - Булево - Отказ
            Процедура ОтразитьДвижения(ДополнительныеСвойства, Движения, Отказ)
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL215"}) if d.code == "BSL215"]
        assert diags == []

    def test_struct_return_fields_do_not_invalidate_params(self, tmp_path: Path) -> None:
        content = """\
            // Описание метода.
            // Параметры:
            //  Реквизиты - Структура - структура реквизитов:
            //    * Период - Дата - дата регистратора
            //  Отказ - Булево
            //
            // Возвращаемое значение:
            //  Неопределено, ТаблицаЗначений - таблица остатков:
            //    * Количество - Число - остаток количества
            Функция Найти(Реквизиты, Отказ)
            КонецФункции
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL215"}) if d.code == "BSL215"]
        assert diags == []

    def test_region_end_comment_is_not_method_description(self, tmp_path: Path) -> None:
        content = """\
            // Конец СтандартныеПодсистемы.РаботаСФайлами
            &НаКлиенте
            Процедура Подключаемый_Нажатие(Элемент, СтандартнаяОбработка)
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL215"}) if d.code == "BSL215"]
        assert diags == []

    def test_param_see_reference_is_empty_description(self, tmp_path: Path) -> None:
        content = """\
            // Описание метода.
            // Параметры:
            //   Ограничение - см. УправлениеДоступомПереопределяемый.Метод.Ограничение.
            Процедура Пример(Ограничение)
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL215"}) if d.code == "BSL215"]
        assert [(d.line, d.character, d.end_character, d.message) for d in diags] == [
            (4, 10, 16, _rule_msg("BSL215")),
            (4, 17, 28, _rule_msg("BSL215")),
        ]

    def test_param_see_reference_without_terminal_dot_is_documented(self, tmp_path: Path) -> None:
        content = """\
            // Описание метода.
            // Параметры:
            //  Параметры - см. Модуль.Метод.Параметры
            Процедура Пример(Параметры)
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL215"}) if d.code == "BSL215"]
        assert diags == []

    def test_tab_indented_param_description_matches_bslls_as_missing(self, tmp_path: Path) -> None:
        content = """\
            // Описание метода.
            // Параметры:
            //\tПараметр - Строка - описание
            Процедура Пример(Параметр)
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL215"}) if d.code == "BSL215"]
        assert [d.message for d in diags] == [_rule_msg("BSL215")]

    def test_legacy_object_module_tab_indented_params_are_documented(self, tmp_path: Path) -> None:
        path = tmp_path / "DataProcessors" / "Обработка" / "Ext" / "ObjectModule.bsl"
        path.parent.mkdir(parents=True)
        path.write_text(
            textwrap.dedent(
                """\
                // Параметры:
                //\t Параметр - Строка\t- описание
                Функция Пример(Параметр) Экспорт
                КонецФункции
                """
            ),
            encoding="utf-8",
        )

        diags = [
            d
            for d in DiagnosticEngine(select={"BSL215"}).check_file(str(path))
            if d.code == "BSL215"
        ]

        assert diags == []

    def test_return_only_doc_block_still_requires_parameter_section(self, tmp_path: Path) -> None:
        content = """\
            // Возвращаемое значение:
            //   Строка - результат.
            Функция Пример(Параметр)
            КонецФункции
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL215"}) if d.code == "BSL215"]
        assert [d.message for d in diags] == [_rule_msg("BSL215")]

    def test_structure_composition_doc_block_does_not_require_parameter_section(
        self, tmp_path: Path
    ) -> None:
        content = """\
            // Состав структуры:
            //   Поле - Строка - значение.
            Функция Пример(Параметр)
            КонецФункции
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL215"}) if d.code == "BSL215"]
        assert diags == []

    def test_param_entry_without_space_after_comment_marker_is_documented(
        self, tmp_path: Path
    ) -> None:
        content = """\
            // Описание метода.
            // Параметры:
            //Параметр - Строка - описание
            Процедура Пример(Параметр)
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL215"}) if d.code == "BSL215"]
        assert diags == []


# BSL228 — TestBsl228OrderOfParams
class TestBsl228OrderOfParams:
    def test_reports_parameter_list_range(self, tmp_path: Path) -> None:
        content = """\
            Функция Тест(Знач Парам1 = Неопределено, Знач Парам2)
                Возврат Парам2;
            КонецФункции
        """
        diags = _check(content, tmp_path, select={"BSL228"})
        bsl228 = [d for d in diags if d.code == "BSL228"]
        assert len(bsl228) == 1
        line = "Функция Тест(Знач Парам1 = Неопределено, Знач Парам2)"
        assert bsl228[0].severity == Severity.WARNING
        assert bsl228[0].message == _rule_msg("BSL228")
        assert bsl228[0].character == line.index("(") + 1
        assert bsl228[0].end_character == line.rindex(")")

    def test_string_default_value_does_not_filter_diagnostic(self, tmp_path: Path) -> None:
        content = """\
            Функция Тест(Парам1 = "значение", Парам2)
                Возврат Парам2;
            КонецФункции
        """
        diags = _check(content, tmp_path, select={"BSL228"})
        assert [d.code for d in diags] == ["BSL228"]

    def test_required_parameters_before_optional_do_not_report(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест(Парам1, Парам2 = Неопределено)
            КонецПроцедуры
        """

        diags = _check(content, tmp_path, select={"BSL228"})

        assert "BSL228" not in _codes(diags)

    def test_all_optional_parameters_do_not_report(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест(Парам1 = Неопределено, Парам2 = 1)
            КонецПроцедуры
        """

        diags = _check(content, tmp_path, select={"BSL228"})

        assert "BSL228" not in _codes(diags)

    def test_multiline_parameter_list_reports_parameter_range(self, tmp_path: Path) -> None:
        content = """\
            Функция Тест(
                Парам1 = Неопределено,
                Парам2)
                Возврат Парам2;
            КонецФункции
        """

        diags = [d for d in _check(content, tmp_path, select={"BSL228"}) if d.code == "BSL228"]

        assert len(diags) == 1
        assert (diags[0].line, diags[0].character) == (2, 4)
        assert (diags[0].end_line, diags[0].end_character) == (3, 10)


# BSL233 — TestBsl233PublicMethodsDescription
class TestBsl233PublicMethodsDescription:
    def test_export_method_in_public_region_without_description_reports(
        self, tmp_path: Path
    ) -> None:
        content = """\
            #Область ПрограммныйИнтерфейс
            Процедура Команда() Экспорт
            КонецПроцедуры
            #КонецОбласти
        """

        diags = [d for d in _check(content, tmp_path, select={"BSL233"}) if d.code == "BSL233"]

        assert len(diags) == 1
        assert diags[0].message == _rule_msg("BSL233")
        assert (diags[0].line, diags[0].character, diags[0].end_character) == (2, 10, 17)

    def test_documented_export_method_in_public_region_does_not_report(
        self, tmp_path: Path
    ) -> None:
        content = """\
            #Область ПрограммныйИнтерфейс
            // Описание метода.
            Процедура Команда() Экспорт
            КонецПроцедуры
            #КонецОбласти
        """

        diags = _check(content, tmp_path, select={"BSL233"})

        assert "BSL233" not in _codes(diags)

    def test_non_export_method_in_public_region_does_not_report(self, tmp_path: Path) -> None:
        content = """\
            #Область ПрограммныйИнтерфейс
            Процедура Команда()
            КонецПроцедуры
            #КонецОбласти
        """

        diags = _check(content, tmp_path, select={"BSL233"})

        assert "BSL233" not in _codes(diags)

    def test_export_method_outside_public_region_does_not_report(self, tmp_path: Path) -> None:
        content = """\
            #Область СлужебныеПроцедурыИФункции
            Процедура Команда() Экспорт
            КонецПроцедуры
            #КонецОбласти
        """

        diags = _check(content, tmp_path, select={"BSL233"})

        assert "BSL233" not in _codes(diags)

    def test_compiler_directive_between_description_and_method_is_allowed(
        self, tmp_path: Path
    ) -> None:
        content = """\
            #Область ПрограммныйИнтерфейс
            // Описание метода.
            &НаКлиенте
            Процедура Команда() Экспорт
            КонецПроцедуры
            #КонецОбласти
        """

        diags = _check(content, tmp_path, select={"BSL233"})

        assert "BSL233" not in _codes(diags)

    def test_see_reference_inside_structured_description_is_allowed(self, tmp_path: Path) -> None:
        content = """\
            #Область ПрограммныйИнтерфейс
            // Возвращает данные.
            //
            // Параметры:
            //  Параметр - Структура - данные. См. НовыйПараметр()
            //
            // Возвращаемое значение:
            // см. НовыйРезультат() - результат.
            Функция Данные(Параметр) Экспорт
            КонецФункции
            #КонецОбласти
        """

        diags = _check(content, tmp_path, select={"BSL233"})

        assert "BSL233" not in _codes(diags)


# BSL007 — TestBsl007UnusedLocalVariableParity
class TestBsl007UnusedLocalVariableParity:
    def test_unused_var_detected(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Перем НеИспользуемая;
                Сообщение("ок");
            КонецПроцедуры
        """
        diags = _check(content, tmp_path)
        bsl007 = [d for d in diags if d.code == "BSL007"]
        assert len(bsl007) >= 1
        assert bsl007[0].message == _rule_msg("BSL007")

    def test_used_var_no_warning(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Перем Результат;
                Результат = 42;
                Сообщение(Результат);
            КонецПроцедуры
        """
        diags = _check(content, tmp_path)
        assert "BSL007" not in _codes(diags)

    def test_perem_assign_without_read_still_unused(self, tmp_path: Path) -> None:
        """LHS of ``А = 1`` must not count as a read of ``А`` (BSLLS-style)."""
        content = """\
            Процедура Тест()
                Перем А;
                А = 1;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL007"})
        assert "BSL007" in _codes(diags)

    def test_implicit_local_assign_unused(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                А = 1 + 2;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL007"})
        assert "BSL007" in _codes(diags)

    def test_implicit_local_self_call_initializer_is_unused(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Кэш = Кэш();
            КонецПроцедуры
        """

        diags = _check(content, tmp_path, select={"BSL007"})
        assert "BSL007" in _codes(diags)

    def test_bare_function_call_name_does_not_count_as_variable_read(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Кэш = Неопределено;
                Результат = Кэш();
                Сообщить(Результат);
            КонецПроцедуры
        """

        diags = [d for d in _check(content, tmp_path, select={"BSL007"}) if d.code == "BSL007"]
        assert [(d.line, d.character, d.end_character) for d in diags] == [
            (2, 4, 7),
        ]

    def test_module_var_assignment_without_read_is_unused(self, tmp_path: Path) -> None:
        content = """\
            Перем КоординатыВыделения;

            Процедура Тест()
                КоординатыВыделения = Новый Структура;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL007"})
        assert "BSL007" in _codes(diags)

    def test_module_var_declaration_unused_reported(self, tmp_path: Path) -> None:
        content = """\
            Перем КэшЗначений;

            Процедура Тест()
                Сообщение("ок");
            КонецПроцедуры
        """

        diags = [d for d in _check(content, tmp_path, select={"BSL007"}) if d.code == "BSL007"]

        assert [(d.line, d.character, d.end_character) for d in diags] == [
            (1, 6, 17),
        ]

    def test_module_var_multiline_declaration_reports_each_name(self, tmp_path: Path) -> None:
        content = """\
            Перем
                ПервыйКэш,
                ВторойКэш;
        """

        diags = [d for d in _check(content, tmp_path, select={"BSL007"}) if d.code == "BSL007"]

        assert [(d.line, d.character, d.end_character) for d in diags] == [
            (2, 4, 13),
            (3, 4, 13),
        ]

    def test_module_var_declaration_used_no_warning(self, tmp_path: Path) -> None:
        content = """\
            Перем КэшЗначений;

            Процедура Тест()
                Сообщить(КэшЗначений);
            КонецПроцедуры
        """

        assert "BSL007" not in _codes(_check(content, tmp_path, select={"BSL007"}))

    def test_module_var_export_declaration_no_warning(self, tmp_path: Path) -> None:
        content = "Перем КэшЗначений Экспорт;\n"

        assert "BSL007" not in _codes(_check(content, tmp_path, select={"BSL007"}))

    def test_exported_module_var_assignment_is_not_implicit_local(self, tmp_path: Path) -> None:
        content = """\
            Перем КэшЗначений Экспорт;

            Процедура Тест()
                КэшЗначений = 1;
            КонецПроцедуры
        """

        assert "BSL007" not in _codes(_check(content, tmp_path, select={"BSL007"}))

    def test_module_level_assign_unused(self, tmp_path: Path) -> None:
        content = "А = 1;\n"
        diags = _check(content, tmp_path, select={"BSL007"})
        assert "BSL007" in _codes(diags)

    def test_module_assign_used_in_procedure(self, tmp_path: Path) -> None:
        content = """\
            А = 1;
            Процедура Тест()
                Сообщение(А);
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL007"})
        assert "BSL007" not in _codes(diags)

    def test_for_index_unused_reported(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Для Индекс = 1 По 3 Цикл
                    Сообщить("x");
                КонецЦикла;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL007"})
        assert "BSL007" in _codes(diags)

    def test_for_each_variable_unused_reported(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест(Коллекция)
                Для каждого Элемент Из Коллекция Цикл
                    Сообщить("x");
                КонецЦикла;
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL007"}) if d.code == "BSL007"]
        assert len(diags) == 1
        assert diags[0].message == _rule_msg("BSL007")

    def test_repeated_for_variable_reports_first_symbol(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Для НомУр = 1 По 3 Цикл
                    Сообщить("x");
                КонецЦикла;
                Для НомУр = 1 По 3 Цикл
                    Сообщить("x");
                КонецЦикла;
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL007"}) if d.code == "BSL007"]
        assert len(diags) == 1
        assert diags[0].line == 2

    def test_implicit_local_reports_first_assignment_site(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                А = 1;
                Если Истина Тогда
                    А = 2;
                КонецЕсли;
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL007"}) if d.code == "BSL007"]
        assert len(diags) == 1
        assert diags[0].line == 2

    def test_comment_mention_does_not_mark_variable_as_used(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Перем ИмяСобытия;
                // ИмяСобытия нужно заполнить позже
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL007"}) if d.code == "BSL007"]
        assert len(diags) == 1
        assert diags[0].message == _rule_msg("BSL007")

    def test_member_access_name_does_not_count_as_local_read(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Вложения = ПолучитьВложения();
                Сообщить(ПочтовоеСообщение.Вложения);
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL007"}) if d.code == "BSL007"]
        assert len(diags) == 1
        assert diags[0].message == _rule_msg("BSL007")

    def test_string_assignment_unused_is_not_filtered_out(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                ИмяСобытия = "Проверка подписи";
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL007"}) if d.code == "BSL007"]
        assert len(diags) == 1
        assert diags[0].message == _rule_msg("BSL007")

    def test_query_text_does_not_mark_variable_as_used(self, tmp_path: Path) -> None:
        content = """\
            Функция Тест()
                ВидПакетаID = 1;
                Результат =
                "ВЫБРАТЬ
                |   &ВидПакетаID КАК ВидПакетаID";
                Возврат Результат;
            КонецФункции
        """

        diags = [d for d in _check(content, tmp_path, select={"BSL007"}) if d.code == "BSL007"]
        assert [(d.line, d.character, d.end_character) for d in diags] == [
            (2, 4, 15),
        ]

    def test_query_text_line_keeps_bsl_prefix_reads(self, tmp_path: Path) -> None:
        content = """\
            Функция Тест()
                Разделитель = "";
                Результат = Результат + Разделитель + "ВЫБРАТЬ
                |   Истина КАК Значение";
                Возврат Результат;
            КонецФункции
        """

        assert "BSL007" not in _codes(_check(content, tmp_path, select={"BSL007"}))

    def test_query_text_concatenation_keeps_bsl_tail_reads(self, tmp_path: Path) -> None:
        content = """\
            Функция Тест()
                ИмяТаблицы = "Справочник.Номенклатура";
                ТекстЗапроса = "ВЫБРАТЬ * ИЗ " + ИмяТаблицы + " КАК Данные";
                Возврат ТекстЗапроса;
            КонецФункции
        """

        assert "BSL007" not in _codes(_check(content, tmp_path, select={"BSL007"}))

    def test_query_text_pipe_concatenation_keeps_bsl_tail_reads(self, tmp_path: Path) -> None:
        content = """\
            Функция Тест()
                ИмяТаблицы = "Справочник.Номенклатура";
                ТекстЗапроса =
                "ВЫБРАТЬ
                |ИЗ " + ИмяТаблицы + " КАК Данные";
                Возврат ТекстЗапроса;
            КонецФункции
        """

        assert "BSL007" not in _codes(_check(content, tmp_path, select={"BSL007"}))

    def test_variable_used_as_dynamic_execute_receiver_is_clean(self, tmp_path: Path) -> None:
        content = """\
            Процедура ВыполнитьДинамическийОбработчик(ПараметрыКоманды, ИмяОбработчика)
                ЦелеваяФорма = ПолучитьФорму(ПараметрыКоманды.ИмяМенеджера + ".Форма", , ЭтаФорма, Истина);
                ИмяОбработчика = "ЦелеваяФорма." + ИмяОбработчика;
                Выполнить(ИмяОбработчика + "(ПараметрыВызова)");
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL007"}) if d.code == "BSL007"]
        assert all(d.message == _rule_msg("BSL007") for d in diags)

    def test_plain_string_receiver_name_does_not_count_as_use(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                ЦелеваяФорма = ПолучитьФорму("Форма");
                ИмяОбработчика = "ЦелеваяФорма.";
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL007"}) if d.code == "BSL007"]
        assert any(d.message == _rule_msg("BSL007") for d in diags)

    def test_object_module_is_skipped(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                НеИспользуется = 1;
            КонецПроцедуры
        """
        path = tmp_path / "DataProcessors" / "Обработка" / "Ext" / "ObjectModule.bsl"
        path.parent.mkdir(parents=True)
        path.write_text(textwrap.dedent(content), encoding="utf-8")
        diags = DiagnosticEngine(select={"BSL007"}).check_file(str(path))
        assert "BSL007" not in _codes(diags)

    def test_manager_module_is_checked(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                НеИспользуется = 1;
            КонецПроцедуры
        """
        path = tmp_path / "DataProcessors" / "Обработка" / "Ext" / "ManagerModule.bsl"
        path.parent.mkdir(parents=True)
        path.write_text(textwrap.dedent(content), encoding="utf-8")
        diags = DiagnosticEngine(select={"BSL007"}).check_file(str(path))
        assert "BSL007" in _codes(diags)

    def test_ordinary_form_module_is_checked(self, tmp_path: Path) -> None:
        form_dir = tmp_path / "DataProcessors" / "Обработка" / "Forms" / "Форма" / "Ext"
        form_dir.mkdir(parents=True)
        (form_dir / "Form.xml").write_text(
            "<UseManagedForm>false</UseManagedForm>", encoding="utf-8"
        )
        path = form_dir / "Module.bsl"
        path.write_text(
            textwrap.dedent(
                """\
                Процедура Тест()
                    НеИспользуется = 1;
                КонецПроцедуры
                """
            ),
            encoding="utf-8",
        )

        diags = DiagnosticEngine(select={"BSL007"}).check_file(str(path))
        assert "BSL007" in _codes(diags)

    def test_managed_form_module_is_skipped(self, tmp_path: Path) -> None:
        form_dir = tmp_path / "DataProcessors" / "Обработка" / "Forms" / "Форма" / "Ext"
        form_dir.mkdir(parents=True)
        (form_dir / "Form.xml").write_text(
            "<UseManagedForm>true</UseManagedForm>", encoding="utf-8"
        )
        path = form_dir / "Module.bsl"
        path.write_text(
            textwrap.dedent(
                """\
                Процедура Тест()
                    НеИспользуется = 1;
                КонецПроцедуры
                """
            ),
            encoding="utf-8",
        )

        diags = DiagnosticEngine(select={"BSL007"}).check_file(str(path))
        assert "BSL007" not in _codes(diags)


# BSL008 — TestBsl008TooManyReturnStatements
class TestBsl008TooManyReturnStatements:
    def test_too_many_returns_detected(self, tmp_path: Path) -> None:
        content = """\
            Функция МногоВозвратов(А)
                Если А = 1 Тогда
                    Возврат "один";
                КонецЕсли;
                Если А = 2 Тогда
                    Возврат "два";
                КонецЕсли;
                Если А = 3 Тогда
                    Возврат "три";
                КонецЕсли;
                Возврат "другое";
            КонецФункции
        """
        diags = _check(content, tmp_path, max_returns=3, select={"BSL008"})
        bsl008 = [d for d in diags if d.code == "BSL008"]
        assert len(bsl008) >= 1
        assert bsl008[0].message == _rule_msg("BSL008")

    def test_few_returns_no_warning(self, tmp_path: Path) -> None:
        content = """\
            Функция МалоВозвратов(А)
                Если А = 1 Тогда
                    Возврат "один";
                КонецЕсли;
                Возврат "другое";
            КонецФункции
        """
        diags = _check(content, tmp_path, max_returns=3)
        assert "BSL008" not in _codes(diags)


# BSL015 — TestBsl015NumberOfOptionalParams
class TestBsl015NumberOfOptionalParams:
    def test_too_many_optional_params(self, tmp_path: Path) -> None:
        content = "Процедура Тест(А = 1, Б = 2, В = 3, Г = 4)\nКонецПроцедуры\n"
        diags = _check(content, tmp_path, max_optional_params=3)
        bsl015 = [d for d in diags if d.code == "BSL015"]
        assert len(bsl015) >= 1

    def test_few_optional_params_no_warning(self, tmp_path: Path) -> None:
        content = "Процедура Тест(А, Б = 2, В = 3)\nКонецПроцедуры\n"
        diags = _check(content, tmp_path, max_optional_params=3)
        assert "BSL015" not in _codes(diags)

    def test_multiline_param_list_range_matches_bslls_context(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест(А,
                Б = 2, В = 3,
                Г = 4, Д = 5) Экспорт
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, max_optional_params=3) if d.code == "BSL015"]
        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (1, 15, 3, 16)
        ]

    def test_multiline_param_list_open_paren_line_range_starts_at_first_param(
        self, tmp_path: Path
    ) -> None:
        content = """\
            Процедура Тест(
                А,
                Б = 2,
                В = 3,
                Г = 4,
                Д = 5) Экспорт
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, max_optional_params=3) if d.code == "BSL015"]
        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [(2, 4, 6, 9)]

    def test_multiline_param_list_closing_paren_line_range_ends_at_last_param(
        self, tmp_path: Path
    ) -> None:
        content = """\
            Функция Тест(А
                , Б = 2
                , В = 3
                , Г = 4
                , Д = 5
                )
                Возврат А;
            КонецФункции
        """
        diags = [d for d in _check(content, tmp_path, max_optional_params=3) if d.code == "BSL015"]
        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (1, 13, 5, 11)
        ]


# BSL031 — TestBsl031NumberOfParams
class TestBsl031NumberOfParams:
    def test_too_many_params_detected(self, tmp_path: Path) -> None:
        content = "Процедура Тест(А, Б, В, Г, Д, Е, Ж, З)\nКонецПроцедуры\n"
        diags = _check(content, tmp_path, max_params=7)
        bsl031 = [d for d in diags if d.code == "BSL031"]
        assert len(bsl031) >= 1
        assert bsl031[0].message == _rule_msg("BSL031")

    def test_acceptable_params_no_warning(self, tmp_path: Path) -> None:
        content = "Процедура Тест(А, Б, В)\nКонецПроцедуры\n"
        diags = _check(content, tmp_path, max_params=7)
        assert "BSL031" not in _codes(diags)

    def test_multiline_param_list_range_matches_bslls_context(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест(А, Б,
                В, Г, Д,
                Е, Ж, З) Экспорт
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, max_params=7) if d.code == "BSL031"]
        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (1, 15, 3, 11)
        ]


# BSL194, BSL224, BSL227 — TestMethodAndStatementMessageParity
class TestMethodAndStatementMessageParity:
    def test_bsl194_severity_and_message_match_bslls(self, tmp_path: Path) -> None:
        content = """\
            Функция Тест()
                Если Истина Тогда
                    Возврат Истина;
                КонецЕсли;
                Возврат Истина;
            КонецФункции
        """

        bsl194 = [d for d in _check(content, tmp_path, select={"BSL194"}) if d.code == "BSL194"]

        assert len(bsl194) == 1
        assert bsl194[0].severity is Severity.ERROR
        assert bsl194[0].message == _rule_msg("BSL194")

    def test_bsl224_constructor_message_matches_bslls(self, tmp_path: Path) -> None:
        content = """\
            Процедура ОбработкаКоманды(ПараметрыВыполненияКоманды)
                ИсточникКоманды = ПараметрыВыполненияКоманды.Источник;
                ПараметрыФормы = Новый Структура("Отбор", Новый Структура(
                    "Организация, ПодразделениеОрганизации",
                    ИсточникКоманды.Объект.Владелец,
                    ИсточникКоманды.Параметры.Ключ));
            КонецПроцедуры
        """

        bsl224 = [d for d in _check(content, tmp_path, select={"BSL224"}) if d.code == "BSL224"]

        assert len(bsl224) == 1
        assert bsl224[0].message == _rule_msg("BSL224")

    def test_bsl227_message_matches_bslls(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                А = 1; Б = 2;
            КонецПроцедуры
        """

        bsl227 = [d for d in _check(content, tmp_path, select={"BSL227"}) if d.code == "BSL227"]

        assert len(bsl227) == 1
        assert bsl227[0].message == _rule_msg("BSL227")


# BSL224 — TestBsl224NestedFunctionInParameters
class TestBsl224NestedFunctionInParameters:
    def test_multiline_argument_with_nested_call_reports(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Результат = ВыполнитьКоманду(
                    ПодготовитьПараметр(
                        Источник));
            КонецПроцедуры
        """

        diags = [d for d in _check(content, tmp_path, select={"BSL224"}) if d.code == "BSL224"]

        assert len(diags) == 1
        assert diags[0].line == 2
        assert diags[0].message == _rule_msg("BSL224")

    def test_oneline_nested_call_is_allowed_by_default(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Результат = ВыполнитьКоманду(ПодготовитьПараметр(Источник));
            КонецПроцедуры
        """

        diags = _check(content, tmp_path, select={"BSL224"})

        assert "BSL224" not in _codes(diags)

    def test_allowed_nstr_call_does_not_report(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Результат = ВыполнитьКоманду(
                    НСтр(
                        "ru = 'Текст'"));
            КонецПроцедуры
        """

        diags = _check(content, tmp_path, select={"BSL224"})

        assert "BSL224" not in _codes(diags)

    def test_allowed_predefined_value_call_does_not_report(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Результат = ВыполнитьКоманду(
                    ПредопределенноеЗначение(
                        "Перечисление.Виды.Значение"));
            КонецПроцедуры
        """

        diags = _check(content, tmp_path, select={"BSL224"})

        assert "BSL224" not in _codes(diags)

    def test_call_like_text_inside_string_does_not_report(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Результат = ВыполнитьКоманду(
                    "ПодготовитьПараметр(Источник)");
            КонецПроцедуры
        """

        diags = _check(content, tmp_path, select={"BSL224"})

        assert "BSL224" not in _codes(diags)

    def test_constructor_anchor_uses_cst_name_not_first_text_match(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Запрос = Новый Запрос(
                    ПодготовитьТекст(
                        Источник));
            КонецПроцедуры
        """

        diags = [d for d in _check(content, tmp_path, select={"BSL224"}) if d.code == "BSL224"]

        assert len(diags) == 1
        line = "    Запрос = Новый Запрос("
        assert diags[0].character == line.rindex("Запрос")
        assert diags[0].end_character == line.rindex("Запрос") + len("Запрос")


# BSL062 — TestBsl062UnusedParameter
class TestBsl062UnusedParameter:
    def test_no_parameter_method_does_not_collect_body_identifiers(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        import onec_hbk_bsl.analysis.diagnostics as diagnostics_module

        def unexpected_collection(*args, **kwargs):
            raise AssertionError("identifier facts must stay lazy for methods without parameters")

        monkeypatch.setattr(
            diagnostics_module,
            "_collect_identifier_casefolds_in_proc_body",
            unexpected_collection,
        )
        content = "Процедура Тест()\n    А = 1;\nКонецПроцедуры\n"

        assert _check(content, tmp_path, select={"BSL062"}) == []

    def test_synthetic_fixture_reports_unused_param_exact_range(self) -> None:
        path = Path("tests/fixtures/diag_synthetic/bsl062_unused_parameter.bsl")
        diags = [
            d
            for d in DiagnosticEngine(select={"BSL062"}).check_file(str(path))
            if d.code == "BSL062"
        ]

        assert len(diags) == 1
        assert diags[0].line == 1
        assert diags[0].character == 15
        assert diags[0].end_character == 29

    def test_unused_param_detected(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест(НеИспользуемый)
                А = 1;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL062"})
        assert "BSL062" in _codes(diags)

    def test_used_param_no_warning(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест(Значение)
                А = Значение + 1;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL062"})
        assert "BSL062" not in _codes(diags)

    def test_underscore_param_reported_bslls_parity(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест(_НеИспользуемый)
                А = 1;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL062"})
        assert "BSL062" in _codes(diags)

    def test_no_params_no_warning(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                А = 1;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL062"})
        assert "BSL062" not in _codes(diags)

    def test_comma_in_default_string_does_not_create_spurious_param(self, tmp_path: Path) -> None:
        """Regression: naive split(',') saw `Р = ","` as two params and flagged ``"``."""
        content = """\
            Функция РазделитьСтрокуЛок(Знач Строка, Разделитель = ",", ВключатьПустые = Истина)
                Если ВключатьПустые Тогда
                    Возврат Строка;
                Иначе
                    Возврат Разделитель;
                КонецЕсли;
            КонецФункции
        """
        diags = _check(content, tmp_path, select={"BSL062"})
        assert "BSL062" not in _codes(diags)

    def test_double_val_prefix_still_recognizes_param_for_bsl062(self, tmp_path: Path) -> None:
        """Typo ``Знач Знач Имя``: regex param list must still see ``Имя`` (not drop it)."""
        content = """\
            Функция РазделитьСтрокуЛок(Знач Знач Строка, Разделитель = ",", ВключатьПустые = Истина)
                Если ВключатьПустые Тогда
                    Возврат Строка;
                Иначе
                    Возврат Разделитель;
                КонецЕсли;
            КонецФункции
        """
        diags = _check(content, tmp_path, select={"BSL062"})
        assert "BSL062" not in _codes(diags)

    def test_unused_parameters_reported_in_client_command_handler(self, tmp_path: Path) -> None:
        content = """\
            &НаКлиенте
            Процедура ОбработкаКоманды(ПараметрКоманды, ПараметрыВыполненияКоманды, Параметры)
                А = 1;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL062"})
        assert [d.message for d in diags if d.code == "BSL062"] == [
            _rule_msg("BSL062"),
            _rule_msg("BSL062"),
            _rule_msg("BSL062"),
        ]

    def test_unused_parameters_reported_in_export_notify_completion_handler(
        self, tmp_path: Path
    ) -> None:
        content = """\
            &НаКлиенте
            Процедура МояОперацияЗавершение(Результат, Параметры) Экспорт
                А = Результат;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL062"})
        assert [d.message for d in diags if d.code == "BSL062"] == [_rule_msg("BSL062")]

    def test_optional_param_flagged_bslls_parity(self, tmp_path: Path) -> None:
        content = """\
            Функция ВычислитьЦену(Количество, Скидка = 0, Валюта = Неопределено)
                Возврат Количество;
            КонецФункции
        """
        diags = _check(content, tmp_path, select={"BSL062"})
        assert [d.message for d in diags if d.code == "BSL062"] == [
            _rule_msg("BSL062"),
            _rule_msg("BSL062"),
        ]

    def test_command_param_reported_bslls_parity(self, tmp_path: Path) -> None:
        content = """\
            &НаКлиенте
            Процедура Сохранить(Команда)
                А = 1;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL062"})
        assert "BSL062" in _codes(diags)

    def test_dopolnitelnye_parametry_reported_bslls_parity(self, tmp_path: Path) -> None:
        content = """\
            &НаКлиенте
            Процедура ОткрытьЗавершение(Отказ, ДополнительныеПараметры) Экспорт
                Сообщить("ok");
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL062"})
        assert [d.message for d in diags if d.code == "BSL062"] == [
            _rule_msg("BSL062"),
            _rule_msg("BSL062"),
        ]

    def test_on_object_create_handler_skipped_bslls_parity(self, tmp_path: Path) -> None:
        content = """\
            Процедура ПриСозданииОбъекта(НеИспользуемый)
                А = 1;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL062"})
        assert "BSL062" not in _codes(diags)

    def test_empty_body_skipped_bslls_parity(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест(НеИспользуемый)
                // Пока пусто.
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL062"})
        assert "BSL062" not in _codes(diags)

    def test_unused_param_skips_split_fragment(self, tmp_path: Path) -> None:
        ext = tmp_path / "CommonModules" / "Модуль" / "Ext"
        ext.mkdir(parents=True)
        (ext / "Module.bsl").write_text("// full module\n", encoding="utf-8")
        path = ext / "Метод.bsl"
        path.write_text(
            textwrap.dedent(
                """\
                Процедура Метод(НеИспользуемый)
                    А = 1;
                КонецПроцедуры
                """
            ),
            encoding="utf-8",
        )
        diags = DiagnosticEngine(select={"BSL062"}).check_file(str(path))
        assert "BSL062" not in _codes(diags)


# BSL254 — TestBsl254TransferringParameters
class TestBsl254TransferringParameters:
    def _check_indexed(
        self,
        tmp_path: Path,
        files: dict[str, str],
        *,
        target: str,
    ) -> list[Diagnostic]:
        idx = SymbolIndex(db_path=":memory:")
        indexer = IncrementalIndexer(index=idx, quiet=True)
        try:
            for name, content in files.items():
                path = tmp_path / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(textwrap.dedent(content), encoding="utf-8")
                indexer.index_file(str(path))
            engine = DiagnosticEngine(select={"BSL254"}, symbol_index=idx)
            return engine.check_file(str(tmp_path / target))
        finally:
            idx.close()

    def test_only_server_method_called_from_client_is_reported(self, tmp_path: Path) -> None:
        diags = self._check_indexed(
            tmp_path,
            {
                "Module.bsl": """\
                    &НаКлиенте
                    Процедура Клиент()
                        Сервер(Документ);
                    КонецПроцедуры

                    &НаСервере
                    Процедура Сервер(Документ)
                        Возврат;
                    КонецПроцедуры
                """,
            },
            target="Module.bsl",
        )
        assert _codes(diags) == ["BSL254"]
        assert diags[0].message == _rule_msg("BSL254")

    def test_server_method_without_client_call_is_not_reported(self, tmp_path: Path) -> None:
        diags = self._check_indexed(
            tmp_path,
            {
                "Module.bsl": """\
                    &НаСервере
                    Процедура Сервер(Документ)
                        Возврат;
                    КонецПроцедуры
                """,
            },
            target="Module.bsl",
        )
        assert "BSL254" not in _codes(diags)

    def test_multiline_server_signature_reports_each_missing_param_at_its_line(
        self, tmp_path: Path
    ) -> None:
        diags = self._check_indexed(
            tmp_path,
            {
                "Module.bsl": """\
                    &НаКлиенте
                    Процедура Клиент()
                        Сервер(Адрес, Истина, Неопределено);
                    КонецПроцедуры

                    &НаСервере
                    Функция Сервер(
                            Адрес,
                            ВыводитьОшибку = Истина,
                            ТипАрхива = Неопределено)
                        Возврат Неопределено;
                    КонецФункции
                """,
            },
            target="Module.bsl",
        )
        bsl254 = [d for d in diags if d.code == "BSL254"]
        assert [d.line for d in bsl254] == [8, 9, 10]
        assert [d.message for d in bsl254] == [
            _rule_msg("BSL254"),
            _rule_msg("BSL254"),
            _rule_msg("BSL254"),
        ]

    def test_reassigned_parameter_is_not_reported(self, tmp_path: Path) -> None:
        diags = self._check_indexed(
            tmp_path,
            {
                "Module.bsl": """\
                    &НаКлиенте
                    Процедура Клиент()
                        Сервер(Документ);
                    КонецПроцедуры

                    &НаСервере
                    Процедура Сервер(Документ)
                        Документ = Неопределено;
                    КонецПроцедуры
                """,
            },
            target="Module.bsl",
        )
        assert "BSL254" not in _codes(diags)

    def test_at_server_no_context_method_called_from_client_is_reported(
        self, tmp_path: Path
    ) -> None:
        diags = self._check_indexed(
            tmp_path,
            {
                "Module.bsl": """\
                    &НаКлиенте
                    Процедура Клиент()
                        Сервер(Документ);
                    КонецПроцедуры

                    &НаСервереБезКонтекста
                    Процедура Сервер(Документ)
                        Возврат;
                    КонецПроцедуры
                """,
            },
            target="Module.bsl",
        )
        assert _codes(diags) == ["BSL254"]

    def test_external_caller_uses_snapshot_procedure_cache(self, tmp_path: Path) -> None:
        diags = self._check_indexed(
            tmp_path,
            {
                "Caller.bsl": """\
                    &НаКлиенте
                    Процедура Клиент()
                        Сервер(Документ);
                    КонецПроцедуры
                """,
                "Server.bsl": """\
                    &НаСервере
                    Процедура Сервер(Документ)
                        Возврат;
                    КонецПроцедуры
                """,
            },
            target="Server.bsl",
        )
        assert _codes(diags) == ["BSL254"]


# BSL266 — TestBsl266UsingCancelParameter
class TestBsl266UsingCancelParameter:
    def test_assigning_false_to_cancel_reports(self, tmp_path: Path) -> None:
        content = """\
            Процедура ПередЗаписью(Отказ)
                Отказ = Ложь;
            КонецПроцедуры
        """

        diags = [d for d in _check(content, tmp_path, select={"BSL266"}) if d.code == "BSL266"]

        assert len(diags) == 1
        assert diags[0].message == _rule_msg("BSL266")
        assert (diags[0].line, diags[0].character) == (2, 4)

    def test_assigning_true_to_cancel_does_not_report(self, tmp_path: Path) -> None:
        content = """\
            Процедура ПередЗаписью(Отказ)
                Отказ = Истина;
            КонецПроцедуры
        """

        diags = _check(content, tmp_path, select={"BSL266"})

        assert "BSL266" not in _codes(diags)

    def test_multiline_cancel_default_is_not_body_assignment(self, tmp_path: Path) -> None:
        content = """\
            Функция Сообщение(
                    Текст,
                    Отказ = Ложь)
                Отказ = Истина;
                Возврат Текст;
            КонецФункции
        """

        diags = _check(content, tmp_path, select={"BSL266"})

        assert "BSL266" not in _codes(diags)

    def test_accumulating_cancel_with_or_does_not_report(self, tmp_path: Path) -> None:
        content = """\
            Процедура ПередЗаписью(Отказ)
                Отказ = Отказ Или Не Проверить();
            КонецПроцедуры
        """

        diags = _check(content, tmp_path, select={"BSL266"})

        assert "BSL266" not in _codes(diags)

    def test_assignment_without_cancel_parameter_does_not_report(self, tmp_path: Path) -> None:
        content = """\
            Процедура ПередЗаписью(Результат)
                Результат = Ложь;
            КонецПроцедуры
        """

        diags = _check(content, tmp_path, select={"BSL266"})

        assert "BSL266" not in _codes(diags)

    def test_english_cancel_false_reports(self, tmp_path: Path) -> None:
        content = """\
            Procedure BeforeWrite(Cancel)
                Cancel = False;
            EndProcedure
        """

        diags = [d for d in _check(content, tmp_path, select={"BSL266"}) if d.code == "BSL266"]

        assert len(diags) == 1
        assert diags[0].message == _rule_msg("BSL266")


# BSL240 — TestBsl240RewriteMethodParameter
class TestBsl240RewriteMethodParameter:
    def test_multiline_param_default_not_false_positive(self, tmp_path: Path) -> None:
        """Continuation lines of the parameter list must not count as body assignments."""
        content = """\
            Процедура МояПроцедура(
                Переменная = Неопределено) Экспорт
                А = 1;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL240"})
        assert "BSL240" not in _codes(diags)

    def test_val_param_overwrite_detected(self, tmp_path: Path) -> None:
        # Знач param overwritten before first use — BSLLS flags this
        content = """\
            Процедура Тест(Знач П) Экспорт
                П = 1;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL240"})
        assert "BSL240" in _codes(diags)

    def test_non_val_param_reassign_not_detected(self, tmp_path: Path) -> None:
        # Non-Знач params can be output params — BSLLS does not flag them
        content = """\
            Процедура Тест(П) Экспорт
                П = 1;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL240"})
        assert "BSL240" not in _codes(diags)

    def test_val_param_read_before_write_not_flagged(self, tmp_path: Path) -> None:
        """Знач-параметр читается до перезаписи — не ошибка."""
        content = """\
            Процедура Тест(Знач Строка)
                Строка = СокрЛП(Строка);
                Сообщить(Строка);
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL240"})
        assert "BSL240" not in _codes(diags)

    def test_val_param_condition_read_before_write_not_flagged(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест(Знач П)
                Если П = Неопределено Тогда
                    П = 1;
                КонецЕсли;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL240"})
        assert "BSL240" not in _codes(diags)

    def test_optional_val_param_overwrite_detected(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест(Знач П = 1)
                П = 2;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL240"})
        assert "BSL240" in _codes(diags)

    def test_val_param_overwrite_detected_in_form_module(self, tmp_path: Path) -> None:
        content = """\
            Процедура ПриОткрытии(Знач Отказ)
                Отказ = Истина;
            КонецПроцедуры
        """
        form_dir = tmp_path / "Catalogs" / "Foo" / "Forms" / "ФормаЭлемента" / "Ext"
        form_dir.mkdir(parents=True)
        bsl_path = form_dir / "Module.bsl"
        bsl_path.write_text(textwrap.dedent(content), encoding="utf-8")
        diags = DiagnosticEngine(select={"BSL240"}).check_file(str(bsl_path))
        assert "BSL240" in _codes(diags)

    def test_val_param_overwrite_after_many_lines_detected(self, tmp_path: Path) -> None:
        body = "\n".join(f"    Локальная{i} = {i};" for i in range(20))
        content = f"""\
            Процедура Тест(Знач П)
        {body}
                П = 1;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL240"})
        assert "BSL240" in _codes(diags)

    def test_val_param_rhs_read_prevents_later_overwrite_warning(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест(Знач П)
                П = СокрЛП(П);
                П = 1;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL240"})
        assert "BSL240" not in _codes(diags)
