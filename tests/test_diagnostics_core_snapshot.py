"""Core snapshot fact diagnostics."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from onec_hbk_bsl.analysis.diagnostics import (
    DiagnosticEngine,
    path_is_likely_form_module_bsl,
)
from tests.diagnostic_test_support import _check, _codes, _rule_msg

pytestmark = pytest.mark.integration


# BSL204 — TestBsl204InvalidCharacterInFile
class TestBsl204InvalidCharacterInFile:
    def test_escaped_quote_string_span(self, tmp_path: Path) -> None:
        content = 'Процедура Тест()\n\tНСтр("ru=\'текст "" – хвост\'") +\nКонецПроцедуры\n'
        diags = _check(content, tmp_path, select={"BSL204"})
        bsl204 = [d for d in diags if d.code == "BSL204"]
        assert len(bsl204) == 1
        assert bsl204[0].line == 2
        assert bsl204[0].character == content.splitlines()[1].index('"')
        assert bsl204[0].end_character == content.splitlines()[1].rindex('"') + 1


# BSL011 — TestBsl011CognitiveComplexity
class TestBsl011CognitiveComplexity:
    def test_high_complexity_detected(self, tmp_path: Path) -> None:
        # Each nested if adds 1 + nesting_level
        content = """\
            Функция Сложная(А, Б, В)
                Если А Тогда
                    Если Б Тогда
                        Если В Тогда
                            Если А И Б Тогда
                                Если В И А Тогда
                                    Возврат 1;
                                КонецЕсли;
                            КонецЕсли;
                        КонецЕсли;
                    КонецЕсли;
                КонецЕсли;
                Пока А > 0 Цикл
                    Если Б Тогда
                        Если В Тогда
                            А = А - 1;
                        КонецЕсли;
                    КонецЕсли;
                КонецЦикла;
                Возврат 0;
            КонецФункции
        """
        diags = _check(content, tmp_path, max_cognitive_complexity=5)
        bsl011 = [d for d in diags if d.code == "BSL011"]
        assert len(bsl011) >= 1
        assert bsl011[0].message == _rule_msg("BSL011")

    def test_simple_function_no_warning(self, tmp_path: Path) -> None:
        content = """\
            Функция Простая(А)
                Если А > 0 Тогда
                    Возврат А;
                КонецЕсли;
                Возврат 0;
            КонецФункции
        """
        diags = _check(content, tmp_path, max_cognitive_complexity=15)
        assert "BSL011" not in _codes(diags)

    def test_ternary_counts_with_current_nesting(self, tmp_path: Path) -> None:
        content = """\
            Функция Сложная(А, Б)
                Если А Тогда
                    Если Б Тогда
                        Результат = ?(А, 1, 0);
                    КонецЕсли;
                КонецЕсли;
                Возврат Результат;
            КонецФункции
        """
        diags = _check(content, tmp_path, max_cognitive_complexity=5, select={"BSL011"})
        bsl011 = [d for d in diags if d.code == "BSL011"]
        assert len(bsl011) == 1
        assert bsl011[0].message == _rule_msg("BSL011")

    def test_ternary_with_space_counts_with_current_nesting(self, tmp_path: Path) -> None:
        content = """\
            Функция Сложная(А, Б)
                Если А Тогда
                    Если Б Тогда
                        Результат = ? (А, 1, 0);
                    КонецЕсли;
                КонецЕсли;
                Возврат Результат;
            КонецФункции
        """
        diags = _check(content, tmp_path, max_cognitive_complexity=5, select={"BSL011"})
        bsl011 = [d for d in diags if d.code == "BSL011"]
        assert len(bsl011) == 1
        assert bsl011[0].message == _rule_msg("BSL011")

    def test_multiline_same_boolean_run_not_counted_twice(self, tmp_path: Path) -> None:
        content = """\
            Функция Простая(А, Б, В)
                Результат = А И Б
                    И НЕ В;
                Возврат Результат;
            КонецФункции
        """
        diags = _check(content, tmp_path, max_cognitive_complexity=1, select={"BSL011"})
        assert "BSL011" not in _codes(diags)

    def test_multiline_nested_ternary_keeps_ternary_nesting(self, tmp_path: Path) -> None:
        content = """\
            Функция Сложная(А, Б, В)
                Если А Тогда
                    Результат = ?(А, 1,
                        ?(Б, 2, ?(В, 3, 0)));
                КонецЕсли;
                Возврат Результат;
            КонецФункции
        """
        diags = _check(content, tmp_path, max_cognitive_complexity=7, select={"BSL011"})
        bsl011 = [d for d in diags if d.code == "BSL011"]
        assert len(bsl011) == 1
        assert bsl011[0].message == _rule_msg("BSL011")

    def test_try_does_not_count_but_except_counts_structurally(self, tmp_path: Path) -> None:
        content = """\
            Функция Сложная()
                Попытка
                    Результат = 1;
                Исключение
                    Результат = 0;
                КонецПопытки;
                Возврат Результат;
            КонецФункции
        """
        diags = _check(content, tmp_path, max_cognitive_complexity=0, select={"BSL011"})
        bsl011 = [d for d in diags if d.code == "BSL011"]
        assert len(bsl011) == 1
        assert bsl011[0].message == _rule_msg("BSL011")

    def test_inline_empty_except_closes_nesting_on_same_line(self, tmp_path: Path) -> None:
        content = """\
            Функция Простая(Условие)
                Если Условие Тогда
                    Если Условие Тогда
                        Попытка
                            Результат = 1;
                        Исключение КонецПопытки;
                    КонецЕсли;
                КонецЕсли;
                Если Условие Тогда
                    Результат = 2;
                КонецЕсли;
                Возврат Результат;
            КонецФункции
        """
        diags = _check(content, tmp_path, max_cognitive_complexity=7, select={"BSL011"})
        assert "BSL011" not in _codes(diags)

    def test_bslls_block_on_closes_cognitive_complexity_suppression(
        self,
        tmp_path: Path,
    ) -> None:
        content = """\
            // BSLLS:CognitiveComplexity-off
            Функция Простая()
                Возврат 1;
            КонецФункции
            // BSLLS:CognitiveComplexity-on

            Функция Сложная(А, Б, В)
                Если А Тогда
                    Если Б Тогда
                        Если В Тогда
                            Если А И Б Тогда
                                Если В И А Тогда
                                    Возврат 1;
                                КонецЕсли;
                            КонецЕсли;
                        КонецЕсли;
                    КонецЕсли;
                КонецЕсли;
                Возврат 0;
            КонецФункции
        """
        diags = _check(content, tmp_path, max_cognitive_complexity=5, select={"BSL011"})
        bsl011 = [d for d in diags if d.code == "BSL011"]
        assert len(bsl011) == 1
        assert bsl011[0].line == 7

    def test_bslls_trailing_off_suppresses_only_current_line_for_bsl011(
        self,
        tmp_path: Path,
    ) -> None:
        content = """\
            Функция Первая(А, Б, В) // BSLLS:CognitiveComplexity-off
                Если А Тогда
                    Если Б Тогда
                        Если В Тогда
                            Если А И Б Тогда
                                Если В И А Тогда
                                    Возврат 1;
                                КонецЕсли;
                            КонецЕсли;
                        КонецЕсли;
                    КонецЕсли;
                КонецЕсли;
                Возврат 0;
            КонецФункции

            Функция Вторая(А, Б, В)
                Если А Тогда
                    Если Б Тогда
                        Если В Тогда
                            Если А И Б Тогда
                                Если В И А Тогда
                                    Возврат 1;
                                КонецЕсли;
                            КонецЕсли;
                        КонецЕсли;
                    КонецЕсли;
                КонецЕсли;
                Возврат 0;
            КонецФункции
        """
        diags = _check(content, tmp_path, max_cognitive_complexity=5, select={"BSL011"})
        bsl011 = [d for d in diags if d.code == "BSL011"]
        assert len(bsl011) == 1
        assert bsl011[0].line == 16

    def test_complex_module_body_reports_like_bslls(self, tmp_path: Path) -> None:
        content = """\
            Если Истина Тогда
                Если Истина Тогда
                    Если Истина Тогда
                        Если Истина Тогда
                            Если Истина Тогда
                                Если Истина Тогда
                                    А = 1;
                                КонецЕсли;
                            КонецЕсли;
                        КонецЕсли;
                    КонецЕсли;
                КонецЕсли;
            КонецЕсли;
        """
        diags = _check(content, tmp_path, max_cognitive_complexity=15, select={"BSL011"})
        bsl011 = [d for d in diags if d.code == "BSL011"]
        assert len(bsl011) == 1
        assert bsl011[0].line == 1
        assert bsl011[0].character == 0
        assert bsl011[0].end_character == 4

    def test_complex_module_body_before_method_reports_once(self, tmp_path: Path) -> None:
        content = """\
            Если Истина Тогда
                Если Истина Тогда
                    Если Истина Тогда
                        Если Истина Тогда
                            Если Истина Тогда
                                Если Истина Тогда
                                    А = 1;
                                КонецЕсли;
                            КонецЕсли;
                        КонецЕсли;
                    КонецЕсли;
                КонецЕсли;
            КонецЕсли;

            Процедура Простая()
                А = 1;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, max_cognitive_complexity=15, select={"BSL011"})
        bsl011 = [d for d in diags if d.code == "BSL011"]
        assert len(bsl011) == 1
        assert bsl011[0].line == 1

    def test_module_body_comment_tokens_do_not_count(self, tmp_path: Path) -> None:
        content = """\
            // Если Истина Тогда Если Истина Тогда Если Истина Тогда
            // Если Истина Тогда Если Истина Тогда Если Истина Тогда
            Процедура Простая()
                А = 1;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, max_cognitive_complexity=0, select={"BSL011"})
        assert "BSL011" not in _codes(diags)


# BSL012 — TestBsl012HardcodeCredentials
class TestBsl012HardcodeCredentials:
    def test_password_detected(self, tmp_path: Path) -> None:
        content = 'Пароль = "секретный123";\n'
        diags = _check(content, tmp_path)
        bsl012 = [d for d in diags if d.code == "BSL012"]
        assert len(bsl012) >= 1

    def test_password_detected_english(self, tmp_path: Path) -> None:
        content = 'Password = "abcdefghij0123456789";\n'
        diags = _check(content, tmp_path)
        assert "BSL012" in _codes(diags)

    def test_token_not_detected_by_default_search_words(self, tmp_path: Path) -> None:
        content = 'token = "abcdefghij0123456789";\n'
        diags = _check(content, tmp_path)
        assert "BSL012" not in _codes(diags)

    def test_empty_string_no_warning(self, tmp_path: Path) -> None:
        content = 'Пароль = "";\n'
        diags = _check(content, tmp_path)
        assert "BSL012" not in _codes(diags)

    def test_masked_password_no_warning(self, tmp_path: Path) -> None:
        content = 'Пароль = "**********";\n'
        diags = _check(content, tmp_path)
        assert "BSL012" not in _codes(diags)

    def test_secure_storage_read_no_warning(self, tmp_path: Path) -> None:
        content = "Пароль = Пароли.Пароль;\n"
        diags = _check(content, tmp_path)
        assert "BSL012" not in _codes(diags)

    def test_structure_key_detected(self, tmp_path: Path) -> None:
        content = 'Структура = Новый Структура("Пароль", "12345");\n'
        diags = _check(content, tmp_path)
        assert "BSL012" in _codes(diags)

    def test_insert_key_detected(self, tmp_path: Path) -> None:
        content = 'Структура.Вставить("Пароль", "12345");\n'
        diags = _check(content, tmp_path)
        assert "BSL012" in _codes(diags)

    def test_in_comment_ignored(self, tmp_path: Path) -> None:
        content = '// Пароль = "секрет";\n'
        diags = _check(content, tmp_path)
        assert "BSL012" not in _codes(diags)


# BSL013 — TestBsl013CommentedCode
class TestBsl013CommentedCode:
    """Tests use select= to keep BSL013 assertions isolated."""

    def test_commented_block_detected(self, tmp_path: Path) -> None:
        content = """\
            // Процедура Старая()
            //     Сообщение("устаревший");
            // КонецПроцедуры
            Процедура Новая()
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL013"})
        bsl013 = [d for d in diags if d.code == "BSL013"]
        assert len(bsl013) >= 1

    def test_bslls_documented_if_block_detected(self, tmp_path: Path) -> None:
        content = """\
            Процедура ПередУдалением(Отказ)
            //    Если Истина Тогда
            //        Сообщить("Для отладки");
            //    КонецЕсли;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL013"})
        bsl013 = [d for d in diags if d.code == "BSL013"]
        assert [(d.line, d.character, d.end_line, d.end_character) for d in bsl013] == [
            (2, 0, 4, 16)
        ]

    def test_bslls_like_single_commented_call_detected(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
            // Сообщить("Для отладки");
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL013"})
        bsl013 = [d for d in diags if d.code == "BSL013"]
        assert [(d.line, d.character, d.end_line, d.end_character) for d in bsl013] == [
            (2, 0, 2, 27)
        ]

    def test_single_comment_no_warning(self, tmp_path: Path) -> None:
        content = """\
            // TODO: реализовать
            Процедура Тест()
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL013"})
        assert "BSL013" not in _codes(diags)

    def test_incomplete_expression_fragment_is_not_commented_code(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Результат = НСтр("ru='До '") +
                //НСтр("ru='Закомментировано '") +
                НСтр("ru='После'");
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL013"})
        assert "BSL013" not in _codes(diags)

    def test_inline_non_bsl_expression_fragment_is_not_commented_code(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                ПолныйКод = Код + 1; // shl(ПолныйКод, 6) + (Код & 0x3F)
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL013"})
        assert "BSL013" not in _codes(diags)

    def test_inline_prose_comment_after_code_is_not_commented_code(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Результат = Код + 1; // смещение байта для следующего шага
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL013"})
        assert "BSL013" not in _codes(diags)

    def test_query_keyword_prefix_is_not_code(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                // Изменения в оформлении ячеек: установка значения "НетЛинии" для
                // свойства "ГраницаСнизу" (в случае задания номеров специальных колонок):
                Сообщить("OK");
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL013"})
        assert "BSL013" not in _codes(diags)

    def test_documentation_example_call_is_not_commented_code(self, tmp_path: Path) -> None:
        content = """\
            // Параметры:
            //  Организация - ссылка.
            //
            // Пример:
            //  РегламентированнаяОтчетность.ПолучитьСсылкуНаРеглОтчет("РСВ", Организация);
            //
            Функция Тест(Организация) Экспорт
            КонецФункции
        """
        diags = _check(content, tmp_path, select={"BSL013"})
        assert "BSL013" not in _codes(diags)

    def test_prose_with_embedded_expression_is_not_commented_code(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                // Специальная обработка автоматически задаваемого номера:
                // "Приложение" - в случае ВРег(СокрЛП(ИмяФормы)) = ВРег("ФормаОтчета2025Кв1")
                Сообщить("OK");
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL013"})
        assert "BSL013" not in _codes(diags)

    def test_commented_annotation_is_included_with_commented_method(self, tmp_path: Path) -> None:
        content = """\
            // &НаКлиенте
            // Процедура СтарыйКод()
            // КонецПроцедуры
            Процедура Тест()
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL013"})
        bsl013 = [d for d in diags if d.code == "BSL013"]
        assert len(bsl013) == 1
        assert bsl013[0].line == 1
        assert bsl013[0].end_line == 3

    def test_commented_preprocessor_block_is_commented_code(self, tmp_path: Path) -> None:
        content = """\
            // #Если Сервер Тогда
            // #КонецЕсли
            Процедура Тест()
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL013"})
        bsl013 = [d for d in diags if d.code == "BSL013"]
        assert [(d.line, d.character, d.end_line, d.end_character) for d in bsl013] == [
            (1, 0, 2, 13)
        ]

    def test_markdown_heading_comment_is_not_commented_code(self, tmp_path: Path) -> None:
        content = """\
            // # Настройка формы
            // Описание поведения команды.
            Процедура Тест()
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL013"})
        assert "BSL013" not in _codes(diags)


# BSL014 — TestBsl014LineTooLong
class TestBsl014LineTooLong:
    def test_long_line_detected(self, tmp_path: Path) -> None:
        long_line = "А = " + "Б + " * 30 + "В;\n"
        content = f"Процедура Тест()\n    {long_line}\nКонецПроцедуры\n"
        diags = _check(content, tmp_path, max_line_length=80)
        bsl014 = [d for d in diags if d.code == "BSL014"]
        assert len(bsl014) >= 1
        assert bsl014[0].message == _rule_msg("BSL014")

    def test_short_line_no_warning(self, tmp_path: Path) -> None:
        content = "Процедура Тест()\n    А = 1;\nКонецПроцедуры\n"
        diags = _check(content, tmp_path, max_line_length=120)
        assert "BSL014" not in _codes(diags)

    def test_line_exactly_at_limit_no_warning(self, tmp_path: Path) -> None:
        line = "А = " + ("1" * 20) + ";\n"
        assert len(line.rstrip()) == 25
        content = f"Процедура Тест()\n{line}КонецПроцедуры\n"
        diags = _check(content, tmp_path, max_line_length=25, select={"BSL014"})
        assert "BSL014" not in _codes(diags)

    def test_trailing_spaces_do_not_count_in_bslls_message(self, tmp_path: Path) -> None:
        content = "Процедура Тест()\n\tА = 12345678901234567890;   \nКонецПроцедуры\n"
        diags = _check(content, tmp_path, max_line_length=25, select={"BSL014"})
        bsl014 = [d for d in diags if d.code == "BSL014"]
        assert len(bsl014) == 1
        assert bsl014[0].message == _rule_msg("BSL014")
        assert bsl014[0].end_character == 26

    def test_query_text_keyword_line_exception_no_warning(self, tmp_path: Path) -> None:
        query_line = "|" + "ВЫБРАТЬ " + ("Поле, " * 30) + "\n"
        assert len(query_line.rstrip()) > 80
        content = f'Запрос.Текст = "\n{query_line}";\n'
        diags = _check(content, tmp_path, max_line_length=80, select={"BSL014"})
        assert "BSL014" not in _codes(diags)

    def test_query_text_non_keyword_continuation_exception_no_warning(self, tmp_path: Path) -> None:
        query_line = "|" + ("x" * 141) + "\n"
        content = f'Запрос.Текст = "\n|ВЫБРАТЬ\n{query_line}";\n'
        diags = _check(content, tmp_path, max_line_length=80, select={"BSL014"})
        assert "BSL014" not in _codes(diags)

    def test_ordinary_multiline_string_pipe_line_detected(self, tmp_path: Path) -> None:
        string_line = "|" + ("x" * 90) + "\n"
        content = f'Сообщение = "\n{string_line}";\n'
        diags = _check(content, tmp_path, max_line_length=80, select={"BSL014"})
        bsl014 = [d for d in diags if d.code == "BSL014"]
        assert len(bsl014) == 1
        assert bsl014[0].line == 2
        assert bsl014[0].end_character == 91

    def test_query_text_pipe_line_still_excluded(self, tmp_path: Path) -> None:
        query_line = "|" + ("Поле, " * 20) + "\n"
        content = f'Запрос.Текст = "\n|ВЫБРАТЬ\n{query_line}";\n'
        diags = _check(content, tmp_path, max_line_length=80, select={"BSL014"})
        assert "BSL014" not in _codes(diags)


# BSL016 — TestBsl016NonStandardRegion
class TestBsl016NonStandardRegion:
    def test_custom_region_detected(self, tmp_path: Path) -> None:
        content = """\
            #Область МояНестандартнаяОбласть
            Процедура Тест()
            КонецПроцедуры
            #КонецОбласти
        """
        path = tmp_path / "AccumulationRegisters" / "Foo" / "Ext" / "ManagerModule.bsl"
        path.parent.mkdir(parents=True)
        path.write_text(textwrap.dedent(content), encoding="utf-8")
        diags = DiagnosticEngine(select={"BSL016"}).check_file(str(path))
        bsl016 = [d for d in diags if d.code == "BSL016"]
        assert len(bsl016) >= 1
        assert bsl016[0].message == _rule_msg("BSL016")

    def test_standard_region_no_warning(self, tmp_path: Path) -> None:
        content = """\
            #Область ПрограммныйИнтерфейс
            Процедура Тест() Экспорт
            КонецПроцедуры
            #КонецОбласти
        """
        diags = _check(content, tmp_path, select={"BSL016"})
        assert "BSL016" not in _codes(diags)

    def test_manager_module_initialize_region_allowed(self, tmp_path: Path) -> None:
        content = """\
            #Область Инициализация
            Процедура ПриСоздании() Экспорт
            КонецПроцедуры
            #КонецОбласти
        """
        path = tmp_path / "AccumulationRegisters" / "Foo" / "Ext" / "ManagerModule.bsl"
        path.parent.mkdir(parents=True)
        path.write_text(textwrap.dedent(content), encoding="utf-8")
        diags = DiagnosticEngine(select={"BSL016"}).check_file(str(path))
        assert "BSL016" not in _codes(diags)

    def test_nested_custom_region_is_not_module_level(self, tmp_path: Path) -> None:
        content = """\
            #Область ПрограммныйИнтерфейс
            #Область Вложенная
            Процедура А() Экспорт
            КонецПроцедуры
            #КонецОбласти
            #КонецОбласти
        """
        path = tmp_path / "CommonModules" / "Модуль" / "Ext" / "Module.bsl"
        path.parent.mkdir(parents=True)
        path.write_text(textwrap.dedent(content), encoding="utf-8")
        diags = DiagnosticEngine(select={"BSL016"}).check_file(str(path))
        assert "BSL016" not in _codes(diags)


# BSL017 — TestBsl017ExportInCommandModule
class TestBsl017ExportInCommandModule:
    def test_export_in_form_module_detected(self, tmp_path: Path) -> None:
        bsl_file = tmp_path / "МояФорма.bsl"
        content = "Процедура Обработать() Экспорт\nКонецПроцедуры\n"
        bsl_file.write_text(content, encoding="utf-8")
        engine = DiagnosticEngine()
        diags = engine.check_file(str(bsl_file))
        bsl017 = [d for d in diags if d.code == "BSL017"]
        assert len(bsl017) >= 1

    def test_no_export_in_form_module_no_warning(self, tmp_path: Path) -> None:
        bsl_file = tmp_path / "МояФорма.bsl"
        content = "Процедура Обработать()\nКонецПроцедуры\n"
        bsl_file.write_text(content, encoding="utf-8")
        engine = DiagnosticEngine()
        diags = engine.check_file(str(bsl_file))
        assert "BSL017" not in [d.code for d in diags]

    def test_export_in_regular_module_no_warning(self, tmp_path: Path) -> None:
        bsl_file = tmp_path / "МойМодуль.bsl"
        content = "Процедура Обработать() Экспорт\nКонецПроцедуры\n"
        bsl_file.write_text(content, encoding="utf-8")
        engine = DiagnosticEngine()
        diags = engine.check_file(str(bsl_file))
        assert "BSL017" not in [d.code for d in diags]

    def test_export_in_split_object_fragment_no_warning(self, tmp_path: Path) -> None:
        ext = tmp_path / "DataProcessors" / "Тест" / "Ext"
        ext.mkdir(parents=True)
        (ext / "ObjectModule.bsl").write_text("// full module\n", encoding="utf-8")
        bsl_file = ext / "ЭкспортныйМетод.bsl"
        bsl_file.write_text(
            "Процедура ЭкспортныйМетод() Экспорт\nКонецПроцедуры\n", encoding="utf-8"
        )
        diags = DiagnosticEngine(select={"BSL017"}).check_file(str(bsl_file))
        assert "BSL017" not in [d.code for d in diags]


# BSL019 — TestBsl019CyclomaticComplexity
class TestBsl019CyclomaticComplexity:
    def test_high_complexity_detected(self, tmp_path: Path) -> None:
        content = """\
            Функция Сложная(А, Б, В, Г)
                Если А Тогда
                    Если Б Тогда
                        Если В Тогда
                            Если Г Тогда
                                Возврат 1;
                            КонецЕсли;
                        КонецЕсли;
                    КонецЕсли;
                ИначеЕсли Б И В Тогда
                    Возврат 2;
                ИначеЕсли В Или Г Тогда
                    Возврат 3;
                КонецЕсли;
                Возврат 0;
            КонецФункции
        """
        diags = _check(content, tmp_path, max_mccabe_complexity=5)
        bsl019 = [d for d in diags if d.code == "BSL019"]
        assert len(bsl019) >= 1
        assert bsl019[0].message == _rule_msg("BSL019")

    def test_simple_function_no_warning(self, tmp_path: Path) -> None:
        content = """\
            Функция Простая(А)
                Если А > 0 Тогда
                    Возврат А;
                КонецЕсли;
                Возврат 0;
            КонецФункции
        """
        diags = _check(content, tmp_path, max_mccabe_complexity=10)
        assert "BSL019" not in _codes(diags)

    def test_function_call_parentheses_do_not_duplicate_boolean_cost(self, tmp_path: Path) -> None:
        content = """\
            Функция Проверка(А, Б)
                Если Проверить(А И Б) Тогда
                    Возврат Истина;
                КонецЕсли;
                Возврат Ложь;
            КонецФункции
        """
        diags = _check(content, tmp_path, max_mccabe_complexity=3)
        assert "BSL019" not in _codes(diags)

    def test_grouping_parentheses_duplicate_boolean_cost(self, tmp_path: Path) -> None:
        content = """\
            Функция Проверка(А, Б)
                Если (А И Б) Тогда
                    Возврат Истина;
                КонецЕсли;
                Возврат Ложь;
            КонецФункции
        """
        diags = _check(content, tmp_path, max_mccabe_complexity=3)
        assert "BSL019" in _codes(diags)


# BSL036 — TestBsl036IfConditionComplexityParity
class TestBsl036IfConditionComplexityParity:
    def test_if_condition_with_string_literals_is_reported(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест(ИмяФайлаВРег, РасширениеФайла)
                Если (Лев(ИмяФайлаВРег, 4) = "ПФР_" ИЛИ Лев(ИмяФайлаВРег, 4) = "СФР_")
                    И СтрНайти(ИмяФайлаВРег, "_ОСП_") > 0 И НРег(РасширениеФайла) = ".xml" Тогда
                    Возврат;
                КонецЕсли;
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL036"}) if d.code == "BSL036"]
        assert len(diags) == 1
        assert diags[0].line == 2
        assert diags[0].message == _rule_msg("BSL036")


# BSL022 — TestBsl022UsingModalWindows
class TestBsl022UsingModalWindows:
    def test_preduprezhdenie_detected(self, tmp_path: Path) -> None:
        content = 'Предупреждение("Внимание!");\n'
        diags = _check(content, tmp_path, select={"BSL022"})
        bsl022 = [d for d in diags if d.code == "BSL022"]
        assert [(d.line, d.character, d.end_character) for d in bsl022] == [(1, 0, 27)]

    def test_warning_detected(self, tmp_path: Path) -> None:
        content = 'Warning("Alert!");\n'
        diags = _check(content, tmp_path)
        assert "BSL022" in _codes(diags)

    def test_modal_global_methods_detected(self, tmp_path: Path) -> None:
        content = "\n".join(
            [
                'Вопрос("Продолжить?", РежимДиалогаВопрос.ДаНет);',
                'ОткрытьФормуМодально("Справочник.Номенклатура.ФормаВыбора");',
                "ОткрытьЗначение(Значение);",
                "ВвестиДату(Дата);",
                "ВвестиЗначение(Значение);",
                "ВвестиСтроку(Строка);",
                "ВвестиЧисло(Число);",
                'УстановитьВнешнююКомпоненту("AddIn");',
                "УстановитьРасширениеРаботыСФайлами();",
                "УстановитьРасширениеРаботыСКриптографией();",
                'ПоместитьФайл("ИмяФайла");',
                'DoQueryBox("Continue?");',
                'OpenFormModal("Catalog.Items.Form.ChoiceForm");',
                "OpenValue(Value);",
                "DoMessageBox();",
                "InputDate(Date);",
                "InputValue(Value);",
                "InputString(StringValue);",
                "InputNumber(NumberValue);",
                "InstallAddIn();",
                "InstallFileSystemExtension();",
                "InstallCryptoExtension();",
                "PutFile();",
                "",
            ]
        )

        diags = _check(content, tmp_path, select={"BSL022"})

        assert [d.line for d in diags if d.code == "BSL022"] == list(range(1, 24))

    def test_nested_modal_global_method_detected(self, tmp_path: Path) -> None:
        content = 'Если Вопрос("Продолжить?", РежимДиалогаВопрос.ДаНет) Тогда\nКонецЕсли;\n'
        diags = _check(content, tmp_path, select={"BSL022"})
        bsl022 = [d for d in diags if d.code == "BSL022"]
        assert [(d.line, d.character, d.end_character) for d in bsl022] == [(1, 5, 52)]

    def test_async_replacement_no_warning(self, tmp_path: Path) -> None:
        content = 'ПоказатьВопрос("Продолжить?");\nПоказатьПредупреждение(, "Внимание");\n'
        diags = _check(content, tmp_path, select={"BSL022"})
        assert "BSL022" not in _codes(diags)

    def test_method_call_on_object_no_warning(self, tmp_path: Path) -> None:
        content = 'Диалог.Вопрос("Продолжить?");\n'
        diags = _check(content, tmp_path, select={"BSL022"})
        assert "BSL022" not in _codes(diags)

    def test_modal_method_in_string_no_warning(self, tmp_path: Path) -> None:
        content = 'Сообщить("Вопрос(""Продолжить?"")");\n'
        diags = _check(content, tmp_path, select={"BSL022"})
        assert "BSL022" not in _codes(diags)

    def test_modal_method_in_inline_comment_no_warning(self, tmp_path: Path) -> None:
        content = 'Сообщить("Готово"); // Вопрос("Продолжить?")\n'
        diags = _check(content, tmp_path, select={"BSL022"})
        assert "BSL022" not in _codes(diags)

    def test_soobshchit_no_warning(self, tmp_path: Path) -> None:
        content = 'Сообщить("Готово");\n'
        diags = _check(content, tmp_path)
        assert "BSL022" not in _codes(diags)

    def test_in_comment_ignored(self, tmp_path: Path) -> None:
        content = '// Предупреждение("устарело");\n'
        diags = _check(content, tmp_path)
        assert "BSL022" not in _codes(diags)


# BSL216 — TestBsl216MissingSpace
class TestBsl216MissingSpace:
    def test_semicolon_before_comment_reports_even_with_comment_slash(self, tmp_path: Path) -> None:
        content = 'ПотокXML.ЗаписатьКонецЭлемента();// "ФИО"\n'
        diags = _check(content, tmp_path, select={"BSL216"})
        assert [(d.line, d.character, d.message) for d in diags if d.code == "BSL216"] == [
            (1, 32, _rule_msg("BSL216")),
        ]

    def test_comma_before_string_reports_when_plus_is_inside_string(self, tmp_path: Path) -> None:
        content = 'Результат = ?(Настройки.Погрешность," ± " + Погрешность, "");\n'
        diags = _check(content, tmp_path, select={"BSL216"})
        assert [(d.line, d.character, d.message) for d in diags if d.code == "BSL216"] == [
            (1, 35, _rule_msg("BSL216")),
        ]

    def test_unary_minus_after_indexer_open_bracket_no_warning(self, tmp_path: Path) -> None:
        content = "Значение = Массив[-1];\n"
        diags = _check(content, tmp_path, select={"BSL216"})
        assert "BSL216" not in _codes(diags)


# BSL026 — TestBsl026EmptyRegion
class TestBsl026EmptyRegion:
    def test_empty_region_detected(self, tmp_path: Path) -> None:
        content = """\
            #Область ПустаяОбласть
            #КонецОбласти
        """
        diags = _check(content, tmp_path)
        bsl026 = [d for d in diags if d.code == "BSL026"]
        assert len(bsl026) >= 1
        assert bsl026[0].message == _rule_msg("BSL026")

    def test_region_with_code_no_warning(self, tmp_path: Path) -> None:
        content = """\
            #Область ПрограммныйИнтерфейс
            Процедура Тест() Экспорт
            КонецПроцедуры
            #КонецОбласти
        """
        diags = _check(content, tmp_path)
        assert "BSL026" not in _codes(diags)

    def test_region_with_only_comments_is_empty(self, tmp_path: Path) -> None:
        content = """\
            #Область ТолькоКомментарии
            // Это просто комментарий
            #КонецОбласти
        """
        diags = _check(content, tmp_path)
        assert "BSL026" in _codes(diags)

    def test_empty_region_skips_split_fragment(self, tmp_path: Path) -> None:
        ext = tmp_path / "CommonModules" / "Модуль" / "Ext"
        ext.mkdir(parents=True)
        (ext / "Module.bsl").write_text("// full module\n", encoding="utf-8")
        path = ext / "Метод.bsl"
        path.write_text(
            textwrap.dedent(
                """\
                #Область ПустаяОбласть
                #КонецОбласти
                """
            ),
            encoding="utf-8",
        )
        diags = DiagnosticEngine(select={"BSL026"}).check_file(str(path))
        assert "BSL026" not in _codes(diags)

    def test_nested_empty_regions_are_checked(self, tmp_path: Path) -> None:
        content = """\
            #Область Outer
            #Область Inner
            #КонецОбласти
            #КонецОбласти
        """
        diags = _check(content, tmp_path, select={"BSL026"})
        assert _codes(diags) == ["BSL026", "BSL026"]


# BSL036, BSL153 — TestBsl036ComplexCondition
class TestBsl036ComplexCondition:
    def test_too_many_bool_ops_detected(self, tmp_path: Path) -> None:
        # 4 operators (И, ИЛИ, И, ИЛИ) > max_bool_ops=3
        content = """\
            Процедура Тест(А, Б, В, Г, Д)
                Если А И Б ИЛИ В И Г ИЛИ Д Тогда
                    А = 1;
                КонецЕсли;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, max_bool_ops=3)
        bsl036 = [d for d in diags if d.code == "BSL036"]
        assert [(d.line, d.character, d.end_line, d.end_character) for d in bsl036] == [
            (2, 9, 2, 30)
        ]

    def test_simple_condition_no_warning(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест(А, Б)
                Если А И Б Тогда
                    А = 1;
                КонецЕсли;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, max_bool_ops=3)
        assert "BSL036" not in _codes(diags)

    def test_trailing_comment_bool_words_do_not_count(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест(А, Б, В)
                Если А И Б И В Тогда // и комментарий не часть условия
                    А = 1;
                КонецЕсли;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, max_bool_ops=3, select={"BSL036"})
        assert "BSL036" not in _codes(diags)

    def test_multiline_condition_bool_ops_bslls_alignment(self, tmp_path: Path) -> None:
        """IfConditionComplexity counts ``И``/``ИЛИ`` across lines until ``Тогда``."""
        content = """\
            Процедура Тест()
                Если Ложь Тогда
                ИначеЕсли НЕ Б
                    И В
                    И Г
                    И Д
                    И А Тогда
                КонецЕсли;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, max_bool_ops=3, select={"BSL036"})
        bsl036 = [d for d in diags if d.code == "BSL036"]
        assert [(d.line, d.character, d.end_line, d.end_character) for d in bsl036] == [
            (3, 14, 7, 11)
        ]

    def test_condition_range_starts_after_keyword_alignment_whitespace(
        self, tmp_path: Path
    ) -> None:
        content = "Процедура Тест()\n\tЕсли \tА И Б И В И Г Тогда\n\tКонецЕсли;\nКонецПроцедуры\n"
        diags = _check(content, tmp_path, max_bool_ops=3, select={"BSL036"})
        bsl036 = [d for d in diags if d.code == "BSL036"]
        assert [(d.line, d.character, d.end_line, d.end_character) for d in bsl036] == [
            (2, 7, 2, 20)
        ]

    def test_elsif_range_starts_after_tab_separator(self, tmp_path: Path) -> None:
        content = (
            "Процедура Тест()\n"
            "\tЕсли Ложь Тогда\n"
            "\tИначеЕсли\tА И Б И В И Г Тогда\n"
            "\tКонецЕсли;\n"
            "КонецПроцедуры\n"
        )
        diags = _check(content, tmp_path, max_bool_ops=3, select={"BSL036"})
        bsl036 = [d for d in diags if d.code == "BSL036"]
        assert [(d.line, d.character, d.end_line, d.end_character) for d in bsl036] == [
            (3, 11, 3, 24)
        ]

    def test_multiline_condition_range_ends_before_standalone_then(self, tmp_path: Path) -> None:
        content = (
            "Процедура Тест()\n"
            "\tЕсли А = 1\n"
            "\t\tИли Б = 2\n"
            "\t\tИли В = 3\n"
            "\t\tИли Г = 4\n"
            "\t\tТогда\n"
            "\tКонецЕсли;\n"
            "КонецПроцедуры\n"
        )
        diags = _check(content, tmp_path, max_bool_ops=3, select={"BSL036"})
        bsl036 = [d for d in diags if d.code == "BSL036"]
        assert [(d.line, d.character, d.end_line, d.end_character) for d in bsl036] == [
            (2, 6, 5, 11)
        ]

    def test_multiline_condition_range_skips_blank_lines_before_standalone_then(
        self, tmp_path: Path
    ) -> None:
        content = (
            "Процедура Тест()\n"
            "\tЕсли Ложь\n"
            "\t\tИЛИ А = 1\n"
            "\t\tИ Б = 2\n"
            "\t\t\n"
            "\t\tИЛИ В = 3\n"
            "\t\tИ Г = 4\n"
            "\t\t\n"
            "\t\tТогда\n"
            "\tКонецЕсли;\n"
            "КонецПроцедуры\n"
        )
        diags = _check(content, tmp_path, max_bool_ops=3, select={"BSL036"})
        bsl036 = [d for d in diags if d.code == "BSL036"]
        assert [(d.line, d.character, d.end_line, d.end_character) for d in bsl036] == [
            (2, 6, 7, 9)
        ]

    def test_bsl153_suppressed_on_continuation_of_bsl036_condition(self, tmp_path: Path) -> None:
        """CanonicalSpelling must not fire on ``и`` continuation lines when IfConditionComplexity applies."""
        content = """\
            Процедура Тест()
                Если Ложь Тогда
                ИначеЕсли НЕ Б
                    и В
                    и Г
                    и Д
                    и А Тогда
                КонецЕсли;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, max_bool_ops=3, select={"BSL036", "BSL153"})
        assert "BSL036" in _codes(diags)
        assert "BSL153" not in _codes(diags)


# BSL040 — TestBsl040UsingThisForm
class TestBsl040UsingThisForm:
    def test_this_form_in_common_module_skipped(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                ЭтаФорма.Закрыть();
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL040"})
        assert "BSL040" not in _codes(diags)

    def test_this_form_in_edt_form_module_reported(self, tmp_path: Path) -> None:
        content = """\
            Процедура ПриОткрытии()
                ЭтаФорма.Закрыть();
            КонецПроцедуры
        """
        form_dir = tmp_path / "Catalogs" / "Foo" / "Forms" / "ФормаЭлемента" / "Ext"
        form_dir.mkdir(parents=True)
        bsl_path = form_dir / "Module.bsl"
        bsl_path.write_text(textwrap.dedent(content), encoding="utf-8")
        diags = DiagnosticEngine(select={"BSL040"}).check_file(str(bsl_path))
        assert "BSL040" in _codes(diags)

    def test_this_form_param_suppresses_diagnostic_in_form_module(self, tmp_path: Path) -> None:
        content = """\
            Процедура Команда(ЭтаФорма)
                ЭтаФорма.Закрыть();
            КонецПроцедуры
        """
        form_dir = tmp_path / "Catalogs" / "Foo" / "Forms" / "ФормаЭлемента" / "Ext"
        form_dir.mkdir(parents=True)
        bsl_path = form_dir / "Module.bsl"
        bsl_path.write_text(textwrap.dedent(content), encoding="utf-8")
        diags = DiagnosticEngine(select={"BSL040"}).check_file(str(bsl_path))
        assert "BSL040" not in _codes(diags)

    def test_this_form_skips_split_form_fragment(self, tmp_path: Path) -> None:
        form_dir = tmp_path / "Catalogs" / "Foo" / "Forms" / "ФормаЭлемента" / "Ext"
        form_dir.mkdir(parents=True)
        (form_dir / "Module.bsl").write_text("// full module\n", encoding="utf-8")
        bsl_path = form_dir / "ПриОткрытии.bsl"
        bsl_path.write_text(
            textwrap.dedent(
                """\
                Процедура ПриОткрытии()
                    ЭтаФорма.Закрыть();
                КонецПроцедуры
                """
            ),
            encoding="utf-8",
        )
        diags = DiagnosticEngine(select={"BSL040"}).check_file(str(bsl_path))
        assert "BSL040" not in _codes(diags)

    def test_path_is_likely_form_module_bsl(self, tmp_path: Path) -> None:
        mod = tmp_path / "Forms" / "SomeForm" / "Ext" / "Module.bsl"
        mod.parent.mkdir(parents=True)
        mod.write_text("// ok\n", encoding="utf-8")
        assert path_is_likely_form_module_bsl(str(mod))
        split_form = tmp_path / "Forms" / "SomeForm" / "Ext" / "Команда.bsl"
        split_form.write_text("// ok\n", encoding="utf-8")
        (split_form.parent / "module.header").write_text("// ok\n", encoding="utf-8")
        assert not path_is_likely_form_module_bsl(str(split_form))
        plain = tmp_path / "CommonModules" / "Foo" / "Ext" / "Module.bsl"
        plain.parent.mkdir(parents=True)
        plain.write_text("// ok\n", encoding="utf-8")
        assert not path_is_likely_form_module_bsl(str(plain))
        object_split = (
            tmp_path
            / "DataProcessors"
            / "Foo"
            / "Ext"
            / "ФайлыИнформационнойБазы_ДоступноДобавление.bsl"
        )
        object_split.parent.mkdir(parents=True)
        object_split.write_text("// ok\n", encoding="utf-8")
        assert not path_is_likely_form_module_bsl(str(object_split))


# BSL219 — TestBsl219MissingVariablesDescription
class TestBsl219MissingVariablesDescription:
    def test_export_var_without_description(self, tmp_path: Path) -> None:
        content = """\
            Перем Глоб Экспорт;

            Процедура Тест()
                Возврат;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL219"})
        bsl219 = [d for d in diags if d.code == "BSL219"]
        assert len(bsl219) == 1
        assert bsl219[0].character == 6
        assert bsl219[0].end_character == 18

    def test_export_var_with_preceding_comment_no_bsl219(self, tmp_path: Path) -> None:
        content = """\
            // Описание переменной
            Перем Глоб Экспорт;

            Процедура Тест()
                Возврат;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL219"})
        assert "BSL219" not in _codes(diags)

    def test_module_var_with_inline_comment_no_bsl219(self, tmp_path: Path) -> None:
        content = """\
            Перем Глоб; // Описание переменной
            Процедура Тест()
                Сообщить(Глоб);
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL219"})
        assert "BSL219" not in _codes(diags)

    def test_module_var_group_after_inline_comment_no_bsl219(self, tmp_path: Path) -> None:
        content = """\
            &НаКлиенте
            Перем ОткрытаФорма; // Описание группы переменных
            &НаКлиенте
            Перем КонтекстВыбора;
            Процедура Тест()
                Сообщить(КонтекстВыбора);
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL219"})
        assert "BSL219" not in _codes(diags)

    def test_previous_inline_group_description_does_not_cross_blank_line(
        self, tmp_path: Path
    ) -> None:
        content = """\
            Перем ОткрытаФорма; // Описание группы переменных

            &НаКлиенте
            Перем КонтекстВыбора;
            Процедура Тест()
                Возврат;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL219"})
        bsl219 = [d for d in diags if d.code == "BSL219"]
        assert len(bsl219) == 1
        assert bsl219[0].line == 4

    def test_export_var_with_preceding_triple_comment_no_bsl219(self, tmp_path: Path) -> None:
        content = """\
            /// Описание
            Перем Глоб Экспорт;

            Процедура Тест()
                Возврат;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL219"})
        assert "BSL219" not in _codes(diags)

    def test_non_export_module_var_without_description_reports_bsl219(self, tmp_path: Path) -> None:
        content = """\
            Перем МояПеременная;
            Процедура Тест()
                Сообщить(МояПеременная);
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL219"})
        assert "BSL219" in _codes(diags)

    def test_multiple_module_vars_without_description_report_each_name(
        self, tmp_path: Path
    ) -> None:
        content = """\
            Перем Первый, Второй;
            Процедура Тест()
                Возврат;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL219"})
        bsl219 = [d for d in diags if d.code == "BSL219"]
        assert [(d.character, d.end_character) for d in bsl219] == [(6, 12), (14, 20)]

    def test_multiple_export_module_vars_include_export_in_last_range(self, tmp_path: Path) -> None:
        content = """\
            Перем Первый, Второй Экспорт;
            Процедура Тест()
                Возврат;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL219"})
        bsl219 = [d for d in diags if d.code == "BSL219"]
        assert [(d.character, d.end_character) for d in bsl219] == [(6, 12), (14, 28)]

    def test_multiline_module_vars_report_each_continuation_name(self, tmp_path: Path) -> None:
        content = """\
            Перем
            Первый,
            Второй Экспорт;
            Процедура Тест()
                Возврат;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL219"})
        bsl219 = [d for d in diags if d.code == "BSL219"]
        assert [(d.line, d.character, d.end_character) for d in bsl219] == [
            (2, 0, 6),
            (3, 0, 14),
        ]

    def test_multiline_module_vars_with_inline_descriptions_do_not_report(
        self, tmp_path: Path
    ) -> None:
        content = """\
            Перем
            Первый, // Описание первой переменной
            Второй Экспорт; // Описание второй переменной
            Процедура Тест()
                Возврат;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL219"})
        assert "BSL219" not in _codes(diags)

    def test_variable_description_before_compiler_directive_satisfies_rule(
        self, tmp_path: Path
    ) -> None:
        content = """\
            // Описание переменной
            &НаКлиенте
            Перем Глоб;
            Процедура Тест()
                Возврат;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL219"})
        assert "BSL219" not in _codes(diags)


# BSL131 — TestBsl131DuplicateRegion
class TestBsl131DuplicateRegion:
    def test_duplicate_region_detected(self, tmp_path: Path) -> None:
        content = (
            "#Область Публичный\nА = 1;\n#КонецОбласти\n#Область Public\nБ = 2;\n#КонецОбласти\n"
        )
        p = tmp_path / "test.bsl"
        p.write_text(content, encoding="utf-8")
        from onec_hbk_bsl.analysis.diagnostics import DiagnosticEngine

        diags = DiagnosticEngine(select={"BSL131"}).check_file(str(p))
        bsl131 = [d for d in diags if d.code == "BSL131"]
        assert [(d.line, d.character, d.end_line, d.end_character) for d in bsl131] == [
            (1, 1, 1, 18)
        ]

    def test_unique_region_names_no_warning(self, tmp_path: Path) -> None:
        content = "#Область Первая\nА = 1;\n#КонецОбласти\n#Область Вторая\nБ = 2;\n#КонецОбласти\n"
        p = tmp_path / "test.bsl"
        p.write_text(content, encoding="utf-8")
        from onec_hbk_bsl.analysis.diagnostics import DiagnosticEngine

        diags = DiagnosticEngine(select={"BSL131"}).check_file(str(p))
        assert "BSL131" not in [d.code for d in diags]

    def test_duplicate_empty_region_detected(self, tmp_path: Path) -> None:
        content = (
            "#Область Тест\n"
            "#КонецОбласти\n"
            "#Область Тест\n"
            "Процедура А()\n"
            "КонецПроцедуры\n"
            "#КонецОбласти\n"
        )
        p = tmp_path / "test.bsl"
        p.write_text(content, encoding="utf-8")
        from onec_hbk_bsl.analysis.diagnostics import DiagnosticEngine

        diags = DiagnosticEngine(select={"BSL131"}).check_file(str(p))
        assert [d.code for d in diags] == ["BSL131"]
        assert diags[0].message == _rule_msg("BSL131")
        assert (diags[0].line, diags[0].character, diags[0].end_line, diags[0].end_character) == (
            1,
            1,
            1,
            13,
        )

    def test_duplicate_non_empty_region_detected(self, tmp_path: Path) -> None:
        content = (
            "#Область Тест\n"
            "Процедура А()\n"
            "КонецПроцедуры\n"
            "#КонецОбласти\n"
            "#Область Тест\n"
            "Процедура Б()\n"
            "КонецПроцедуры\n"
            "#КонецОбласти\n"
        )
        p = tmp_path / "test.bsl"
        p.write_text(content, encoding="utf-8")
        from onec_hbk_bsl.analysis.diagnostics import DiagnosticEngine

        diags = DiagnosticEngine(select={"BSL131"}).check_file(str(p))
        assert [d.code for d in diags] == ["BSL131"]
        assert (diags[0].line, diags[0].character, diags[0].end_line, diags[0].end_character) == (
            1,
            1,
            1,
            13,
        )

    def test_standard_region_aliases_detected(self, tmp_path: Path) -> None:
        content = (
            "#Область ОписаниеПеременных\n"
            "Перем А;\n"
            "#КонецОбласти\n"
            "#Region Variables\n"
            "Перем Б;\n"
            "#EndRegion\n"
        )
        p = tmp_path / "test.bsl"
        p.write_text(content, encoding="utf-8")
        from onec_hbk_bsl.analysis.diagnostics import DiagnosticEngine

        diags = DiagnosticEngine(select={"BSL131"}).check_file(str(p))
        assert [d.code for d in diags] == ["BSL131"]
        assert (diags[0].line, diags[0].character, diags[0].end_line, diags[0].end_character) == (
            1,
            1,
            1,
            27,
        )

    def test_third_duplicate_reports_first_region_once(self, tmp_path: Path) -> None:
        content = (
            "#Область Тест\n"
            "А = 1;\n"
            "#КонецОбласти\n"
            "#Область Тест\n"
            "Б = 2;\n"
            "#КонецОбласти\n"
            "#Область Тест\n"
            "В = 3;\n"
            "#КонецОбласти\n"
        )
        p = tmp_path / "test.bsl"
        p.write_text(content, encoding="utf-8")
        from onec_hbk_bsl.analysis.diagnostics import DiagnosticEngine

        diags = DiagnosticEngine(select={"BSL131"}).check_file(str(p))
        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (1, 1, 1, 13)
        ]

    def test_nested_duplicate_regions_are_not_module_level(self, tmp_path: Path) -> None:
        content = (
            "#Область Outer\n"
            "#Область D\n"
            "А = 1;\n"
            "#КонецОбласти\n"
            "#Область D\n"
            "Б = 2;\n"
            "#КонецОбласти\n"
            "#КонецОбласти\n"
        )
        p = tmp_path / "test.bsl"
        p.write_text(content, encoding="utf-8")
        from onec_hbk_bsl.analysis.diagnostics import DiagnosticEngine

        diags = DiagnosticEngine(select={"BSL131"}).check_file(str(p))
        assert "BSL131" not in [d.code for d in diags]


# BSL190 — TestBsl190FormDataToValue
class TestBsl190FormDataToValue:
    def test_form_data_ru_detected(self, tmp_path: Path) -> None:
        content = 'Рез = ДанныеФормыВЗначение(ДанныеФормы, Тип("CatalogObject"));\n'
        diags = _check(content, tmp_path, select={"BSL190"})
        assert "BSL190" in _codes(diags)

    def test_form_data_en_detected(self, tmp_path: Path) -> None:
        content = 'Obj = FormDataToValue(FormData, Type("CatalogObject"));\n'
        diags = _check(content, tmp_path, select={"BSL190"})
        assert "BSL190" in _codes(diags)

    def test_comment_not_detected(self, tmp_path: Path) -> None:
        content = "// ДанныеФормыВЗначение(ДанныеФормы)\n"
        diags = _check(content, tmp_path, select={"BSL190"})
        assert "BSL190" not in _codes(diags)

    def test_string_literal_not_detected(self, tmp_path: Path) -> None:
        content = 'Текст = "ДанныеФормыВЗначение";\n'
        diags = _check(content, tmp_path, select={"BSL190"})
        assert "BSL190" not in _codes(diags)
