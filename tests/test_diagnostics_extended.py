"""
Extended tests for DiagnosticEngine — covers rules BSL003–BSL017.

Each test class covers one rule, with:
  - A positive case (issue detected)
  - A negative case (no false positive)
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from bsl_analyzer.analysis.diagnostics import Diagnostic, DiagnosticEngine

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _engine(**kwargs) -> DiagnosticEngine:
    return DiagnosticEngine(**kwargs)


def _check(content: str, tmp_path: Path, **engine_kwargs) -> list[Diagnostic]:
    """Write *content* to a temp .bsl file and run the diagnostic engine."""
    bsl_file = tmp_path / "test.bsl"
    bsl_file.write_text(textwrap.dedent(content), encoding="utf-8")
    return DiagnosticEngine(**engine_kwargs).check_file(str(bsl_file))


def _codes(diags: list[Diagnostic]) -> list[str]:
    return [d.code for d in diags]


# ---------------------------------------------------------------------------
# BSL003 — NonExportMethodsInApiRegion
# ---------------------------------------------------------------------------


class TestBsl003NonExportInApiRegion:
    def test_missing_export_in_api_region(self, tmp_path: Path) -> None:
        content = """\
            #Область ПрограммныйИнтерфейс

            Процедура МоеАПИ()
                Сообщение("ok");
            КонецПроцедуры

            #КонецОбласти
        """
        diags = _check(content, tmp_path)
        bsl003 = [d for d in diags if d.code == "BSL003"]
        assert len(bsl003) >= 1
        assert "МоеАПИ" in bsl003[0].message

    def test_export_in_api_region_no_warning(self, tmp_path: Path) -> None:
        content = """\
            #Область ПрограммныйИнтерфейс

            Процедура МоеАПИ() Экспорт
                Сообщение("ok");
            КонецПроцедуры

            #КонецОбласти
        """
        diags = _check(content, tmp_path)
        assert "BSL003" not in _codes(diags)

    def test_non_api_region_no_warning(self, tmp_path: Path) -> None:
        content = """\
            #Область СлужебныеПроцедурыИФункции

            Процедура Вспомогательная()
                Сообщение("ok");
            КонецПроцедуры

            #КонецОбласти
        """
        diags = _check(content, tmp_path)
        assert "BSL003" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL005 — HardcodeNetworkAddress
# ---------------------------------------------------------------------------


class TestBsl005HardcodeNetworkAddress:
    def test_url_detected(self, tmp_path: Path) -> None:
        content = 'Адрес = "http://example.com/api";\n'
        diags = _check(content, tmp_path)
        assert "BSL005" in _codes(diags)

    def test_ip_address_detected(self, tmp_path: Path) -> None:
        content = 'Адрес = "192.168.1.100";\n'
        diags = _check(content, tmp_path)
        assert "BSL005" in _codes(diags)

    def test_no_hardcode_no_warning(self, tmp_path: Path) -> None:
        content = 'Адрес = ПолучитьАдрес();\n'
        diags = _check(content, tmp_path)
        assert "BSL005" not in _codes(diags)

    def test_in_comment_ignored(self, tmp_path: Path) -> None:
        content = '// Адрес = "http://example.com";\n'
        diags = _check(content, tmp_path)
        assert "BSL005" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL006 — HardcodePath
# ---------------------------------------------------------------------------


class TestBsl006HardcodePath:
    def test_windows_path_detected(self, tmp_path: Path) -> None:
        content = 'Путь = "C:\\Users\\admin\\file.xlsx";\n'
        diags = _check(content, tmp_path)
        assert "BSL006" in _codes(diags)

    def test_linux_path_detected(self, tmp_path: Path) -> None:
        content = 'Путь = "/home/user/data";\n'
        diags = _check(content, tmp_path)
        assert "BSL006" in _codes(diags)

    def test_relative_path_no_warning(self, tmp_path: Path) -> None:
        content = 'Путь = "data/file.xlsx";\n'
        diags = _check(content, tmp_path)
        assert "BSL006" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL007 — UnusedLocalVariable
# ---------------------------------------------------------------------------


class TestBsl007UnusedLocalVariable:
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
        assert "НеИспользуемая" in bsl007[0].message

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


# ---------------------------------------------------------------------------
# BSL008 — TooManyReturnStatements
# ---------------------------------------------------------------------------


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
        diags = _check(content, tmp_path, max_returns=3)
        bsl008 = [d for d in diags if d.code == "BSL008"]
        assert len(bsl008) >= 1
        assert "МногоВозвратов" in bsl008[0].message

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


# ---------------------------------------------------------------------------
# BSL009 — SelfAssign
# ---------------------------------------------------------------------------


class TestBsl009SelfAssign:
    def test_self_assign_detected(self, tmp_path: Path) -> None:
        content = "Процедура Тест()\n    Переменная = Переменная;\nКонецПроцедуры\n"
        diags = _check(content, tmp_path)
        bsl009 = [d for d in diags if d.code == "BSL009"]
        assert len(bsl009) >= 1
        assert "Переменная" in bsl009[0].message

    def test_normal_assign_no_warning(self, tmp_path: Path) -> None:
        content = "Процедура Тест()\n    А = Б;\nКонецПроцедуры\n"
        diags = _check(content, tmp_path)
        assert "BSL009" not in _codes(diags)

    def test_self_assign_in_comment_ignored(self, tmp_path: Path) -> None:
        content = "// Х = Х;\n"
        diags = _check(content, tmp_path)
        assert "BSL009" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL010 — UselessReturn
# ---------------------------------------------------------------------------


class TestBsl010UselessReturn:
    def test_useless_return_in_procedure(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Сообщение("ok");
                Возврат;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path)
        bsl010 = [d for d in diags if d.code == "BSL010"]
        assert len(bsl010) >= 1

    def test_return_in_function_no_warning(self, tmp_path: Path) -> None:
        """Return at end of function is NOT useless — it carries a value."""
        content = """\
            Функция Тест()
                Возврат 42;
            КонецФункции
        """
        diags = _check(content, tmp_path)
        assert "BSL010" not in _codes(diags)

    def test_return_in_middle_no_warning(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест(А)
                Если А = 0 Тогда
                    Возврат;
                КонецЕсли;
                Сообщение(А);
            КонецПроцедуры
        """
        diags = _check(content, tmp_path)
        assert "BSL010" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL011 — CognitiveComplexity
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# BSL012 — HardcodeCredentials
# ---------------------------------------------------------------------------


class TestBsl012HardcodeCredentials:
    def test_password_detected(self, tmp_path: Path) -> None:
        content = 'Пароль = "секретный123";\n'
        diags = _check(content, tmp_path)
        bsl012 = [d for d in diags if d.code == "BSL012"]
        assert len(bsl012) >= 1

    def test_token_detected(self, tmp_path: Path) -> None:
        content = 'token = "abcdefghij0123456789";\n'
        diags = _check(content, tmp_path)
        assert "BSL012" in _codes(diags)

    def test_empty_string_no_warning(self, tmp_path: Path) -> None:
        content = 'Пароль = "";\n'
        diags = _check(content, tmp_path)
        assert "BSL012" not in _codes(diags)

    def test_in_comment_ignored(self, tmp_path: Path) -> None:
        content = '// Пароль = "секрет";\n'
        diags = _check(content, tmp_path)
        assert "BSL012" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL013 — CommentedCode
# ---------------------------------------------------------------------------


class TestBsl013CommentedCode:
    def test_commented_block_detected(self, tmp_path: Path) -> None:
        content = """\
            // Процедура Старая()
            //     Сообщение("устаревший");
            // КонецПроцедуры
            Процедура Новая()
            КонецПроцедуры
        """
        diags = _check(content, tmp_path)
        bsl013 = [d for d in diags if d.code == "BSL013"]
        assert len(bsl013) >= 1

    def test_single_comment_no_warning(self, tmp_path: Path) -> None:
        """A single comment line is not enough to trigger the rule."""
        content = """\
            // TODO: реализовать
            Процедура Тест()
            КонецПроцедуры
        """
        diags = _check(content, tmp_path)
        assert "BSL013" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL014 — LineTooLong
# ---------------------------------------------------------------------------


class TestBsl014LineTooLong:
    def test_long_line_detected(self, tmp_path: Path) -> None:
        long_line = "А = " + "Б + " * 30 + "В;\n"
        content = f"Процедура Тест()\n    {long_line}\nКонецПроцедуры\n"
        diags = _check(content, tmp_path, max_line_length=80)
        bsl014 = [d for d in diags if d.code == "BSL014"]
        assert len(bsl014) >= 1

    def test_short_line_no_warning(self, tmp_path: Path) -> None:
        content = "Процедура Тест()\n    А = 1;\nКонецПроцедуры\n"
        diags = _check(content, tmp_path, max_line_length=120)
        assert "BSL014" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL015 — NumberOfOptionalParams
# ---------------------------------------------------------------------------


class TestBsl015NumberOfOptionalParams:
    def test_too_many_optional_params(self, tmp_path: Path) -> None:
        content = (
            'Процедура Тест(А = 1, Б = 2, В = 3, Г = 4)\n'
            'КонецПроцедуры\n'
        )
        diags = _check(content, tmp_path, max_optional_params=3)
        bsl015 = [d for d in diags if d.code == "BSL015"]
        assert len(bsl015) >= 1

    def test_few_optional_params_no_warning(self, tmp_path: Path) -> None:
        content = 'Процедура Тест(А, Б = 2, В = 3)\nКонецПроцедуры\n'
        diags = _check(content, tmp_path, max_optional_params=3)
        assert "BSL015" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL016 — NonStandardRegion
# ---------------------------------------------------------------------------


class TestBsl016NonStandardRegion:
    def test_custom_region_detected(self, tmp_path: Path) -> None:
        content = """\
            #Область МояНестандартнаяОбласть
            Процедура Тест()
            КонецПроцедуры
            #КонецОбласти
        """
        diags = _check(content, tmp_path)
        bsl016 = [d for d in diags if d.code == "BSL016"]
        assert len(bsl016) >= 1
        assert "МояНестандартнаяОбласть" in bsl016[0].message

    def test_standard_region_no_warning(self, tmp_path: Path) -> None:
        content = """\
            #Область ПрограммныйИнтерфейс
            Процедура Тест() Экспорт
            КонецПроцедуры
            #КонецОбласти
        """
        diags = _check(content, tmp_path)
        assert "BSL016" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL017 — ExportMethodsInCommandModule
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Rule selection / suppression
# ---------------------------------------------------------------------------


class TestRuleSelection:
    def test_select_limits_rules(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Перем НеИспользуется;
                А = А;
            КонецПроцедуры
        """
        # Only ask for BSL009 (self-assign) — BSL007 (unused var) should be suppressed
        diags = _check(content, tmp_path, select={"BSL009"})
        assert all(d.code == "BSL009" for d in diags)

    def test_ignore_suppresses_rule(self, tmp_path: Path) -> None:
        content = "Пароль = \"секрет123\";\n"
        diags = _check(content, tmp_path, ignore={"BSL012"})
        assert "BSL012" not in _codes(diags)

    def test_noqa_suppresses_inline(self, tmp_path: Path) -> None:
        content = 'Пароль = "секрет123";  // noqa: BSL012\n'
        diags = _check(content, tmp_path)
        assert "BSL012" not in _codes(diags)

    def test_noqa_all_suppresses_all(self, tmp_path: Path) -> None:
        content = 'Пароль = "секрет123";  // noqa\n'
        diags = _check(content, tmp_path)
        # BSL012 should be suppressed (noqa without codes = suppress all)
        bsl012 = [d for d in diags if d.code == "BSL012" and d.line == 1]
        assert bsl012 == []

    def test_bsl_disable_suppresses_inline(self, tmp_path: Path) -> None:
        content = 'Пароль = "секрет123";  // bsl-disable: BSL012\n'
        diags = _check(content, tmp_path)
        assert "BSL012" not in _codes(diags)


# ---------------------------------------------------------------------------
# RULE_METADATA completeness
# ---------------------------------------------------------------------------


class TestRuleMetadata:
    def test_all_rules_have_metadata(self) -> None:
        from bsl_analyzer.analysis.diagnostics import RULE_METADATA

        expected_codes = {f"BSL{i:03d}" for i in range(1, 18)}
        assert expected_codes.issubset(set(RULE_METADATA.keys()))

    def test_metadata_has_required_fields(self) -> None:
        from bsl_analyzer.analysis.diagnostics import RULE_METADATA

        required = {"name", "description", "severity", "sonar_type", "sonar_severity"}
        for code, meta in RULE_METADATA.items():
            missing = required - set(meta.keys())
            assert not missing, f"{code} is missing fields: {missing}"

    def test_all_bsl036_rules_have_metadata(self) -> None:
        from bsl_analyzer.analysis.diagnostics import RULE_METADATA

        expected_codes = {f"BSL{i:03d}" for i in range(1, 37)}
        assert expected_codes.issubset(set(RULE_METADATA.keys()))


# ---------------------------------------------------------------------------
# BSL018 — RaiseWithLiteral
# ---------------------------------------------------------------------------


class TestBsl018RaiseWithLiteral:
    def test_raise_with_string_detected(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                ВызватьИсключение "Ошибка";
            КонецПроцедуры
        """
        diags = _check(content, tmp_path)
        bsl018 = [d for d in diags if d.code == "BSL018"]
        assert len(bsl018) >= 1

    def test_raise_eng_with_string_detected(self, tmp_path: Path) -> None:
        content = """\
            Procedure Test()
                Raise "Error message";
            EndProcedure
        """
        diags = _check(content, tmp_path)
        assert "BSL018" in _codes(diags)

    def test_raise_with_variable_no_warning(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                ВызватьИсключение НовоеИсключение("Ошибка");
            КонецПроцедуры
        """
        diags = _check(content, tmp_path)
        assert "BSL018" not in _codes(diags)

    def test_raise_in_comment_no_warning(self, tmp_path: Path) -> None:
        content = '// ВызватьИсключение "Ошибка";\n'
        diags = _check(content, tmp_path)
        assert "BSL018" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL019 — CyclomaticComplexity
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# BSL020 — ExcessiveNesting
# ---------------------------------------------------------------------------


class TestBsl020ExcessiveNesting:
    def test_deep_nesting_detected(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест(А, Б, В)
                Если А Тогда
                    Если Б Тогда
                        Если В Тогда
                            Если А И Б Тогда
                                А = 1;
                            КонецЕсли;
                        КонецЕсли;
                    КонецЕсли;
                КонецЕсли;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, max_nesting_depth=3)
        bsl020 = [d for d in diags if d.code == "BSL020"]
        assert len(bsl020) >= 1

    def test_shallow_nesting_no_warning(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест(А)
                Если А Тогда
                    А = 1;
                КонецЕсли;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, max_nesting_depth=4)
        assert "BSL020" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL021 — UnusedValParameter
# ---------------------------------------------------------------------------


class TestBsl021UnusedValParameter:
    def test_unused_val_param_detected(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест(Знач НеИспользуется)
                А = 1;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path)
        bsl021 = [d for d in diags if d.code == "BSL021"]
        assert len(bsl021) >= 1
        assert "НеИспользуется" in bsl021[0].message

    def test_used_val_param_no_warning(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест(Знач Параметр)
                А = Параметр + 1;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path)
        assert "BSL021" not in _codes(diags)

    def test_reference_param_not_flagged(self, tmp_path: Path) -> None:
        """Reference params (without Знач) should NOT be flagged."""
        content = """\
            Процедура Тест(НеИспользуется)
                А = 1;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path)
        assert "BSL021" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL022 — DeprecatedMessage
# ---------------------------------------------------------------------------


class TestBsl022DeprecatedMessage:
    def test_preduprezhdenie_detected(self, tmp_path: Path) -> None:
        content = 'Предупреждение("Внимание!");\n'
        diags = _check(content, tmp_path)
        assert "BSL022" in _codes(diags)

    def test_warning_detected(self, tmp_path: Path) -> None:
        content = 'Warning("Alert!");\n'
        diags = _check(content, tmp_path)
        assert "BSL022" in _codes(diags)

    def test_soobshchit_no_warning(self, tmp_path: Path) -> None:
        content = 'Сообщить("Готово");\n'
        diags = _check(content, tmp_path)
        assert "BSL022" not in _codes(diags)

    def test_in_comment_ignored(self, tmp_path: Path) -> None:
        content = '// Предупреждение("устарело");\n'
        diags = _check(content, tmp_path)
        assert "BSL022" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL023 — UsingServiceTag
# ---------------------------------------------------------------------------


class TestBsl023UsingServiceTag:
    def test_todo_detected(self, tmp_path: Path) -> None:
        content = "// TODO: реализовать проверку\nПроцедура Тест()\nКонецПроцедуры\n"
        diags = _check(content, tmp_path)
        assert "BSL023" in _codes(diags)

    def test_fixme_detected(self, tmp_path: Path) -> None:
        content = "// FIXME: баг с кодировкой\nА = 1;\n"
        diags = _check(content, tmp_path)
        assert "BSL023" in _codes(diags)

    def test_hack_detected(self, tmp_path: Path) -> None:
        content = "// HACK: временный обходной путь\nА = 1;\n"
        diags = _check(content, tmp_path)
        assert "BSL023" in _codes(diags)

    def test_normal_comment_no_warning(self, tmp_path: Path) -> None:
        content = "// Обычный комментарий без тегов\nА = 1;\n"
        diags = _check(content, tmp_path)
        assert "BSL023" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL024 — SpaceAtStartComment
# ---------------------------------------------------------------------------


class TestBsl024SpaceAtStartComment:
    def test_no_space_detected(self, tmp_path: Path) -> None:
        content = "//Без пробела\nА = 1;\n"
        diags = _check(content, tmp_path)
        assert "BSL024" in _codes(diags)

    def test_with_space_no_warning(self, tmp_path: Path) -> None:
        content = "// С пробелом\nА = 1;\n"
        diags = _check(content, tmp_path)
        assert "BSL024" not in _codes(diags)

    def test_doc_comment_slash3_no_warning(self, tmp_path: Path) -> None:
        """/// doc-comments are exempted."""
        content = "/// Документация функции\nА = 1;\n"
        diags = _check(content, tmp_path)
        assert "BSL024" not in _codes(diags)

    def test_empty_comment_no_warning(self, tmp_path: Path) -> None:
        """An empty // comment (nothing after) is OK."""
        content = "//\nА = 1;\n"
        diags = _check(content, tmp_path)
        assert "BSL024" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL026 — EmptyRegion
# ---------------------------------------------------------------------------


class TestBsl026EmptyRegion:
    def test_empty_region_detected(self, tmp_path: Path) -> None:
        content = """\
            #Область ПустаяОбласть
            #КонецОбласти
        """
        diags = _check(content, tmp_path)
        bsl026 = [d for d in diags if d.code == "BSL026"]
        assert len(bsl026) >= 1
        assert "ПустаяОбласть" in bsl026[0].message

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


# ---------------------------------------------------------------------------
# BSL027 — UseGotoOperator
# ---------------------------------------------------------------------------


class TestBsl027UseGoto:
    def test_goto_detected(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Перейти ~МетаМетка;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path)
        assert "BSL027" in _codes(diags)

    def test_goto_in_comment_ignored(self, tmp_path: Path) -> None:
        content = "// Перейти ~Метка;\nА = 1;\n"
        diags = _check(content, tmp_path)
        assert "BSL027" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL029 — MagicNumber
# ---------------------------------------------------------------------------


class TestBsl029MagicNumber:
    def test_magic_number_detected(self, tmp_path: Path) -> None:
        content = """\
            Функция Тест()
                Возврат 42;
            КонецФункции
        """
        diags = _check(content, tmp_path)
        assert "BSL029" in _codes(diags)

    def test_zero_one_no_warning(self, tmp_path: Path) -> None:
        content = """\
            Функция Тест()
                Если А = 0 Тогда
                    Возврат 1;
                КонецЕсли;
                Возврат 0;
            КонецФункции
        """
        diags = _check(content, tmp_path)
        assert "BSL029" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL030 — LineEndsWithSemicolon (header semicolon)
# ---------------------------------------------------------------------------


class TestBsl030HeaderSemicolon:
    def test_semicolon_on_header_detected(self, tmp_path: Path) -> None:
        content = "Процедура Тест();\nКонецПроцедуры\n"
        diags = _check(content, tmp_path)
        assert "BSL030" in _codes(diags)

    def test_no_semicolon_no_warning(self, tmp_path: Path) -> None:
        content = "Процедура Тест()\nКонецПроцедуры\n"
        diags = _check(content, tmp_path)
        assert "BSL030" not in _codes(diags)

    def test_export_with_semicolon_detected(self, tmp_path: Path) -> None:
        content = "Процедура Тест() Экспорт;\nКонецПроцедуры\n"
        diags = _check(content, tmp_path)
        assert "BSL030" in _codes(diags)


# ---------------------------------------------------------------------------
# BSL031 — NumberOfParams
# ---------------------------------------------------------------------------


class TestBsl031NumberOfParams:
    def test_too_many_params_detected(self, tmp_path: Path) -> None:
        content = (
            "Процедура Тест(А, Б, В, Г, Д, Е, Ж, З)\n"
            "КонецПроцедуры\n"
        )
        diags = _check(content, tmp_path, max_params=7)
        bsl031 = [d for d in diags if d.code == "BSL031"]
        assert len(bsl031) >= 1
        assert "8" in bsl031[0].message

    def test_acceptable_params_no_warning(self, tmp_path: Path) -> None:
        content = "Процедура Тест(А, Б, В)\nКонецПроцедуры\n"
        diags = _check(content, tmp_path, max_params=7)
        assert "BSL031" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL032 — FunctionReturnValue
# ---------------------------------------------------------------------------


class TestBsl032FunctionReturnValue:
    def test_function_without_return_detected(self, tmp_path: Path) -> None:
        content = """\
            Функция Тест(А)
                А = А + 1;
            КонецФункции
        """
        diags = _check(content, tmp_path)
        assert "BSL032" in _codes(diags)

    def test_function_with_return_no_warning(self, tmp_path: Path) -> None:
        content = """\
            Функция Тест(А)
                Возврат А + 1;
            КонецФункции
        """
        diags = _check(content, tmp_path)
        assert "BSL032" not in _codes(diags)

    def test_procedure_not_flagged(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест(А)
                А = 1;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path)
        assert "BSL032" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL033 — QueryInLoop
# ---------------------------------------------------------------------------


class TestBsl033QueryInLoop:
    def test_query_in_foreach_detected(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест(Коллекция)
                ДляКаждого Элемент Из Коллекция Цикл
                    Результат = Запрос.Выполнить();
                КонецЦикла;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path)
        assert "BSL033" in _codes(diags)

    def test_query_in_while_detected(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Пока Условие Цикл
                    Рез = ЗапросHTTP.Execute();
                КонецЦикла;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path)
        assert "BSL033" in _codes(diags)

    def test_query_outside_loop_no_warning(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Результат = Запрос.Выполнить();
            КонецПроцедуры
        """
        diags = _check(content, tmp_path)
        assert "BSL033" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL034 — UnusedErrorVariable
# ---------------------------------------------------------------------------


class TestBsl034UnusedErrorVariable:
    def test_unused_error_info_detected(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Попытка
                    А = 1;
                Исключение
                    ИнфОшибки = ИнформацияОбОшибке();
                КонецПопытки;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path)
        assert "BSL034" in _codes(diags)

    def test_used_error_info_no_warning(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Попытка
                    А = 1;
                Исключение
                    ИнфОшибки = ИнформацияОбОшибке();
                    ЗаписатьОшибку(ИнфОшибки);
                КонецПопытки;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path)
        assert "BSL034" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL035 — DuplicateStringLiteral
# ---------------------------------------------------------------------------


class TestBsl035DuplicateStringLiteral:
    def test_duplicate_detected(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                А = "ОченьДлиннаяСтрока";
                Б = "ОченьДлиннаяСтрока";
                В = "ОченьДлиннаяСтрока";
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, min_duplicate_uses=3)
        assert "BSL035" in _codes(diags)

    def test_two_uses_no_warning_with_threshold_3(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                А = "ОченьДлиннаяСтрока";
                Б = "ОченьДлиннаяСтрока";
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, min_duplicate_uses=3)
        assert "BSL035" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL036 — ComplexCondition
# ---------------------------------------------------------------------------


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
        assert "BSL036" in _codes(diags)

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
