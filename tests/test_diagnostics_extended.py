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
    """BSL013 is disabled by default — tests use select= to enable it explicitly."""

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

    def test_single_comment_no_warning(self, tmp_path: Path) -> None:
        """A single comment line is not enough to trigger the rule."""
        content = """\
            // TODO: реализовать
            Процедура Тест()
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL013"})
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

    # ── BSLLS block suppression ──────────────────────────────────────────

    def test_bslls_block_off_on(self, tmp_path: Path) -> None:
        """BSLLS:Rule-off suppresses from that line; -on re-enables."""
        content = (
            "// BSLLS:UsingHardcodeSecretInformation-off\n"        # line 1 → BSL012 off
            'Пароль = "СуперСекрет2024!";\n'                       # line 2 → suppressed
            "// BSLLS:UsingHardcodeSecretInformation-on\n"         # line 3 → re-enable
            'ТоженПароль = "МойПароль123@#";\n'                    # line 4 → reported
        )
        diags = _check(content, tmp_path)
        lines_bsl012 = {d.line for d in diags if d.code == "BSL012"}
        assert 2 not in lines_bsl012, "Line 2 must be suppressed by BSLLS block"
        assert 4 in lines_bsl012, "Line 4 must NOT be suppressed after -on"

    def test_bslls_inline_same_line(self, tmp_path: Path) -> None:
        """BSLLS-off at end of line suppresses that line itself."""
        content = 'Пароль = "секрет123";  // BSLLS:UsingHardcodeSecretInformation-off\n'
        diags = _check(content, tmp_path)
        assert "BSL012" not in _codes(diags)

    def test_bslls_all_off(self, tmp_path: Path) -> None:
        """BSLLS-off without rule name suppresses all diagnostics."""
        content = (
            "// BSLLS-off\n"
            'Пароль = "секрет123";\n'
            "// BSLLS-on\n"
        )
        diags = _check(content, tmp_path)
        assert not _codes(diags), "All diagnostics must be suppressed inside BSLLS-off block"

    def test_bslls_russian_flags(self, tmp_path: Path) -> None:
        """BSLLS-выкл/вкл Russian flags are equivalent to off/on."""
        content = (
            "// BSLLS:UsingHardcodeSecretInformation-выкл\n"
            'Пароль = "секрет123";\n'
            "// BSLLS:UsingHardcodeSecretInformation-вкл\n"
        )
        diags = _check(content, tmp_path)
        assert "BSL012" not in _codes(diags)

    def test_bslls_and_noqa_coexist(self, tmp_path: Path) -> None:
        """BSLLS block and noqa can be used together without conflict."""
        content = (
            "// BSLLS:UsingHardcodeSecretInformation-off\n"
            'Пароль = "секрет123";  // noqa: BSL009\n'   # both suppressions active
            "// BSLLS:UsingHardcodeSecretInformation-on\n"
        )
        diags = _check(content, tmp_path)
        assert "BSL012" not in _codes(diags)

    def test_bslls_unknown_name_ignored(self, tmp_path: Path) -> None:
        """Unknown BSLLS names are silently ignored — other rules still fire."""
        content = (
            "// BSLLS:NonExistentRule-off\n"
            'Пароль = "секрет123";\n'
        )
        diags = _check(content, tmp_path)
        assert "BSL012" in _codes(diags)

    def test_bslls_nested_independent_rules(self, tmp_path: Path) -> None:
        """Two rules can be independently nested."""
        content = (
            "// BSLLS:UsingHardcodeSecretInformation-off\n"   # BSL012 off
            "// BSLLS:LineLength-off\n"                        # BSL014 off
            'Пароль = "секрет123";\n'                          # both suppressed
            "// BSLLS:UsingHardcodeSecretInformation-on\n"    # BSL012 back on
            'Токен = "abc";\n'                                 # BSL012 fires, BSL014 still off
            "// BSLLS:LineLength-on\n"
        )
        diags = _check(content, tmp_path)
        # Line 3: both should be suppressed
        assert all(d.code not in {"BSL012", "BSL014"} for d in diags if d.line == 3)
        # Line 5: BSL012 should fire again (if token is a secret-looking string)
        # BSL014 still off → no line-length errors on line 5


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

    def test_all_bsl041_rules_have_metadata(self) -> None:
        from bsl_analyzer.analysis.diagnostics import RULE_METADATA

        expected_codes = {f"BSL{i:03d}" for i in range(1, 42)}
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
        diags = _check(content, tmp_path, select={"BSL018"})
        bsl018 = [d for d in diags if d.code == "BSL018"]
        assert len(bsl018) >= 1

    def test_raise_eng_with_string_detected(self, tmp_path: Path) -> None:
        content = """\
            Procedure Test()
                Raise "Error message";
            EndProcedure
        """
        diags = _check(content, tmp_path, select={"BSL018"})
        assert "BSL018" in _codes(diags)

    def test_raise_with_variable_no_warning(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Текст = "Ошибка";
                ВызватьИсключение Текст;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL018"})
        assert "BSL018" not in _codes(diags)

    def test_raise_with_concatenated_message_no_warning(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                ВызватьИсключение "Префикс: " + Строка(ТипЗнч(А));
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL018"})
        assert "BSL018" not in _codes(diags)

    def test_raise_in_comment_no_warning(self, tmp_path: Path) -> None:
        content = '// ВызватьИсключение "Ошибка";\n'
        diags = _check(content, tmp_path, select={"BSL018"})
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

    def test_duplicate_only_on_raise_lines_no_warning(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                ВызватьИсключение "ОченьДлиннаяСтрока";
                ВызватьИсключение "ОченьДлиннаяСтрока";
                ВызватьИсключение "ОченьДлиннаяСтрока";
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


# ---------------------------------------------------------------------------
# BSL037 — OverrideBuiltinMethod
# ---------------------------------------------------------------------------


class TestBsl037OverrideBuiltin:
    def test_builtin_name_detected(self, tmp_path: Path) -> None:
        content = "Функция Строка(Значение)\nКонецФункции\n"
        diags = _check(content, tmp_path)
        assert "BSL037" in _codes(diags)

    def test_unique_name_no_warning(self, tmp_path: Path) -> None:
        content = "Функция МояФункция(Значение)\nВозврат Значение;\nКонецФункции\n"
        diags = _check(content, tmp_path)
        assert "BSL037" not in _codes(diags)

    def test_message_contains_name(self, tmp_path: Path) -> None:
        content = "Процедура Сообщить(Текст)\nКонецПроцедуры\n"
        diags = _check(content, tmp_path)
        bsl037 = [d for d in diags if d.code == "BSL037"]
        assert bsl037
        assert "Сообщить" in bsl037[0].message


# ---------------------------------------------------------------------------
# BSL038 — StringConcatenationInLoop
# ---------------------------------------------------------------------------


class TestBsl038StringConcatInLoop:
    def test_concat_in_loop_detected(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест(Массив)
                Результат = "";
                ДляКаждого Эл Из Массив Цикл
                    Результат = Результат + "текст";
                КонецЦикла;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path)
        assert "BSL038" in _codes(diags)

    def test_concat_outside_loop_no_warning(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Результат = "А" + "Б";
            КонецПроцедуры
        """
        diags = _check(content, tmp_path)
        assert "BSL038" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL039 — NestedTernaryOperator
# ---------------------------------------------------------------------------


class TestBsl039NestedTernary:
    def test_nested_ternary_detected(self, tmp_path: Path) -> None:
        content = 'А = ?(Б, ?(В, 1, 2), 3);\n'
        diags = _check(content, tmp_path)
        assert "BSL039" in _codes(diags)

    def test_simple_ternary_no_warning(self, tmp_path: Path) -> None:
        content = 'А = ?(Б, 1, 2);\n'
        diags = _check(content, tmp_path)
        assert "BSL039" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL041 — NotifyDescriptionToModalWindow
# ---------------------------------------------------------------------------


class TestBsl041NotifyDescription:
    def test_notify_description_detected(self, tmp_path: Path) -> None:
        content = "ОповещениеОЗакрытии = ОписаниеОповещения(\"ОбработкаЗакрытия\", ЭтотОбъект);\n"
        diags = _check(content, tmp_path)
        assert "BSL041" in _codes(diags)

    def test_in_comment_not_flagged(self, tmp_path: Path) -> None:
        content = "// ОписаниеОповещения(\"ОбработкаЗакрытия\", ЭтотОбъект)\n"
        diags = _check(content, tmp_path)
        assert "BSL041" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL042 — EmptyExportMethod
# ---------------------------------------------------------------------------


class TestBsl042EmptyExportMethod:
    def test_empty_export_method_detected(self, tmp_path: Path) -> None:
        content = """\
            Процедура ПустойМетод() Экспорт
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL042"})
        assert "BSL042" in _codes(diags)

    def test_empty_export_method_with_comment(self, tmp_path: Path) -> None:
        content = """\
            Процедура ПустойМетод() Экспорт
                // TODO: implement
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL042"})
        assert "BSL042" in _codes(diags)

    def test_export_with_body_no_warning(self, tmp_path: Path) -> None:
        content = """\
            Процедура МетодСТелом() Экспорт
                Сообщить("ok");
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL042"})
        assert "BSL042" not in _codes(diags)

    def test_non_export_empty_no_warning(self, tmp_path: Path) -> None:
        content = """\
            Процедура ВнутреннийМетод()
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL042"})
        assert "BSL042" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL043 — TooManyVariables
# ---------------------------------------------------------------------------


class TestBsl043TooManyVariables:
    def test_many_variables_detected(self, tmp_path: Path) -> None:
        vars_decl = "\n".join(
            f"    Перем Переменная{i};" for i in range(16)
        )
        content = f"Процедура Тест()\n{vars_decl}\nКонецПроцедуры\n"
        bsl_file = tmp_path / "test.bsl"
        bsl_file.write_text(content, encoding="utf-8")
        diags = DiagnosticEngine(select={"BSL043"}).check_file(str(bsl_file))
        assert "BSL043" in _codes(diags)

    def test_few_variables_no_warning(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Перем А;
                Перем Б;
                А = 1;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL043"})
        assert "BSL043" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL044 — FunctionNoReturnValue
# ---------------------------------------------------------------------------


class TestBsl044FunctionNoReturnValue:
    def test_export_function_no_return_detected(self, tmp_path: Path) -> None:
        content = """\
            Функция ПолучитьДанные() Экспорт
                ВыполнитьЗапрос();
            КонецФункции
        """
        diags = _check(content, tmp_path, select={"BSL044"})
        assert "BSL044" in _codes(diags)

    def test_export_function_with_return_no_warning(self, tmp_path: Path) -> None:
        content = """\
            Функция ПолучитьДанные() Экспорт
                Возврат 42;
            КонецФункции
        """
        diags = _check(content, tmp_path, select={"BSL044"})
        assert "BSL044" not in _codes(diags)

    def test_non_export_function_no_warning(self, tmp_path: Path) -> None:
        content = """\
            Функция ВнутренняяФункция()
                А = 1;
            КонецФункции
        """
        diags = _check(content, tmp_path, select={"BSL044"})
        assert "BSL044" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL045 — MultilineStringLiteral
# ---------------------------------------------------------------------------


class TestBsl045MultilineStringLiteral:
    def test_string_concat_detected(self, tmp_path: Path) -> None:
        content = 'Текст = "Строка1"\n    + "Строка2";\n'
        bsl_file = tmp_path / "test.bsl"
        bsl_file.write_text(content, encoding="utf-8")
        diags = DiagnosticEngine(select={"BSL045"}).check_file(str(bsl_file))
        assert "BSL045" in _codes(diags)

    def test_non_string_concat_no_warning(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Результат = А + Б;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL045"})
        assert "BSL045" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL046 — MissingElseBranch
# ---------------------------------------------------------------------------


class TestBsl046MissingElseBranch:
    def test_if_elseif_no_else_detected(self, tmp_path: Path) -> None:
        content = """\
            Если А = 1 Тогда
                Б = 1;
            ИначеЕсли А = 2 Тогда
                Б = 2;
            КонецЕсли;
        """
        diags = _check(content, tmp_path, select={"BSL046"})
        assert "BSL046" in _codes(diags)

    def test_if_elseif_with_else_no_warning(self, tmp_path: Path) -> None:
        content = """\
            Если А = 1 Тогда
                Б = 1;
            ИначеЕсли А = 2 Тогда
                Б = 2;
            Иначе
                Б = 0;
            КонецЕсли;
        """
        diags = _check(content, tmp_path, select={"BSL046"})
        assert "BSL046" not in _codes(diags)

    def test_simple_if_no_warning(self, tmp_path: Path) -> None:
        content = """\
            Если А = 1 Тогда
                Б = 1;
            КонецЕсли;
        """
        diags = _check(content, tmp_path, select={"BSL046"})
        assert "BSL046" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL047 — DateTimeNow (CurrentDate)
# ---------------------------------------------------------------------------


class TestBsl047CurrentDate:
    def test_current_date_detected(self, tmp_path: Path) -> None:
        content = "Дата = ТекущаяДата();\n"
        diags = _check(content, tmp_path, select={"BSL047"})
        assert "BSL047" in _codes(diags)

    def test_current_date_in_comment_no_warning(self, tmp_path: Path) -> None:
        content = "// Дата = ТекущаяДата();\n"
        diags = _check(content, tmp_path, select={"BSL047"})
        assert "BSL047" not in _codes(diags)

    def test_universal_date_no_warning(self, tmp_path: Path) -> None:
        content = "Дата = ТекущаяУниверсальнаяДата();\n"
        diags = _check(content, tmp_path, select={"BSL047"})
        assert "BSL047" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL048 — EmptyFile
# ---------------------------------------------------------------------------


class TestBsl048EmptyFile:
    def test_empty_file_detected(self, tmp_path: Path) -> None:
        bsl_file = tmp_path / "empty.bsl"
        bsl_file.write_text("", encoding="utf-8")
        diags = DiagnosticEngine(select={"BSL048"}).check_file(str(bsl_file))
        assert "BSL048" in _codes(diags)

    def test_comments_only_detected(self, tmp_path: Path) -> None:
        content = "// Это комментарий\n// Ещё комментарий\n"
        diags = _check(content, tmp_path, select={"BSL048"})
        assert "BSL048" in _codes(diags)

    def test_file_with_code_no_warning(self, tmp_path: Path) -> None:
        content = "А = 1;\n"
        diags = _check(content, tmp_path, select={"BSL048"})
        assert "BSL048" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL049 — UnconditionalExceptionRaise
# ---------------------------------------------------------------------------


class TestBsl049UnconditionalRaise:
    def test_raise_outside_try_detected(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                ВызватьИсключение "Ошибка";
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL049"})
        assert "BSL049" in _codes(diags)

    def test_raise_inside_try_no_warning(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Попытка
                    ВызватьИсключение "Ошибка";
                Исключение
                    Сообщить(ОписаниеОшибки());
                КонецПопытки;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL049"})
        assert "BSL049" not in _codes(diags)

    def test_raise_inside_nested_block_no_warning(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест(А)
                Если А Тогда
                    ВызватьИсключение "Ошибка";
                КонецЕсли;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL049"})
        assert "BSL049" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL050 — LargeTransaction
# ---------------------------------------------------------------------------


class TestBsl050LargeTransaction:
    def test_begin_without_commit_detected(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                НачатьТранзакцию();
                ЗаписатьДанные();
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL050"})
        assert "BSL050" in _codes(diags)

    def test_begin_with_commit_no_warning(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                НачатьТранзакцию();
                ЗаписатьДанные();
                ЗафиксироватьТранзакцию();
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL050"})
        assert "BSL050" not in _codes(diags)

    def test_begin_with_rollback_no_warning(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                НачатьТранзакцию();
                ЗаписатьДанные();
                ОтменитьТранзакцию();
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL050"})
        assert "BSL050" not in _codes(diags)

    def test_no_transaction_no_warning(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                ЗаписатьДанные();
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL050"})
        assert "BSL050" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL051 — UnreachableCode
# ---------------------------------------------------------------------------


class TestBsl051UnreachableCode:
    def test_code_after_return_detected(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Возврат;
                Сообщить("никогда");
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL051"})
        assert "BSL051" in _codes(diags)

    def test_no_unreachable_code_no_warning(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Сообщить("привет");
                Возврат;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL051"})
        assert "BSL051" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL052 — UselessCondition
# ---------------------------------------------------------------------------


class TestBsl052UselessCondition:
    def test_if_true_detected(self, tmp_path: Path) -> None:
        content = """\
            Если Истина Тогда
                А = 1;
            КонецЕсли;
        """
        diags = _check(content, tmp_path, select={"BSL052"})
        assert "BSL052" in _codes(diags)

    def test_if_false_detected(self, tmp_path: Path) -> None:
        content = """\
            Если Ложь Тогда
                А = 1;
            КонецЕсли;
        """
        diags = _check(content, tmp_path, select={"BSL052"})
        assert "BSL052" in _codes(diags)

    def test_normal_condition_no_warning(self, tmp_path: Path) -> None:
        content = """\
            Если А > 0 Тогда
                Б = 1;
            КонецЕсли;
        """
        diags = _check(content, tmp_path, select={"BSL052"})
        assert "BSL052" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL053 — ExecuteDynamic
# ---------------------------------------------------------------------------


class TestBsl053ExecuteDynamic:
    def test_execute_detected(self, tmp_path: Path) -> None:
        content = 'Выполнить("А = 1;");\n'
        diags = _check(content, tmp_path, select={"BSL053"})
        assert "BSL053" in _codes(diags)

    def test_in_comment_no_warning(self, tmp_path: Path) -> None:
        content = '// Выполнить("А = 1;");\n'
        diags = _check(content, tmp_path, select={"BSL053"})
        assert "BSL053" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL054 — ModuleLevelVariable
# ---------------------------------------------------------------------------


class TestBsl054ModuleLevelVariable:
    def test_module_level_var_detected(self, tmp_path: Path) -> None:
        content = """\
            Перем МояПеременная;
            Процедура Тест()
                Сообщить(МояПеременная);
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL054"})
        assert "BSL054" in _codes(diags)

    def test_local_var_no_warning(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Перем Локальная;
                Локальная = 1;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL054"})
        assert "BSL054" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL055 — ConsecutiveBlankLines
# ---------------------------------------------------------------------------


class TestBsl055ConsecutiveBlankLines:
    def test_many_blank_lines_detected(self, tmp_path: Path) -> None:
        content = "А = 1;\n\n\n\n\nБ = 2;\n"
        bsl_file = tmp_path / "test.bsl"
        bsl_file.write_text(content, encoding="utf-8")
        diags = DiagnosticEngine(select={"BSL055"}).check_file(str(bsl_file))
        assert "BSL055" in _codes(diags)

    def test_two_blank_lines_no_warning(self, tmp_path: Path) -> None:
        content = "А = 1;\n\n\nБ = 2;\n"
        bsl_file = tmp_path / "test.bsl"
        bsl_file.write_text(content, encoding="utf-8")
        diags = DiagnosticEngine(select={"BSL055"}).check_file(str(bsl_file))
        assert "BSL055" not in _codes(diags)

    def test_single_blank_line_no_warning(self, tmp_path: Path) -> None:
        content = "А = 1;\n\nБ = 2;\n"
        bsl_file = tmp_path / "test.bsl"
        bsl_file.write_text(content, encoding="utf-8")
        diags = DiagnosticEngine(select={"BSL055"}).check_file(str(bsl_file))
        assert "BSL055" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL056 — ShortMethodName
# ---------------------------------------------------------------------------


class TestBsl056ShortMethodName:
    def test_short_name_detected(self, tmp_path: Path) -> None:
        content = """\
            Процедура Аб()
                Сообщить("hi");
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL056"})
        assert "BSL056" in _codes(diags)

    def test_single_char_name_detected(self, tmp_path: Path) -> None:
        content = """\
            Функция Ф()
                Возврат 1;
            КонецФункции
        """
        diags = _check(content, tmp_path, select={"BSL056"})
        assert "BSL056" in _codes(diags)

    def test_normal_name_no_warning(self, tmp_path: Path) -> None:
        content = """\
            Процедура ОбработатьЗаказ()
                Сообщить("ok");
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL056"})
        assert "BSL056" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL057 — DeprecatedInputDialog
# ---------------------------------------------------------------------------


class TestBsl057DeprecatedInputDialog:
    def test_input_value_detected(self, tmp_path: Path) -> None:
        content = 'ВвестиЗначение(Значение, "Введите значение");\n'
        diags = _check(content, tmp_path, select={"BSL057"})
        assert "BSL057" in _codes(diags)

    def test_input_number_detected(self, tmp_path: Path) -> None:
        content = 'ВвестиЧисло(Число, "Введите число");\n'
        diags = _check(content, tmp_path, select={"BSL057"})
        assert "BSL057" in _codes(diags)

    def test_in_comment_no_warning(self, tmp_path: Path) -> None:
        content = '// ВвестиЗначение(Значение, "Введите");\n'
        diags = _check(content, tmp_path, select={"BSL057"})
        assert "BSL057" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL058 — QueryWithoutWhere
# ---------------------------------------------------------------------------


class TestBsl058QueryWithoutWhere:
    def test_query_without_where_detected(self, tmp_path: Path) -> None:
        content = '''\
            ТекстЗапроса = "ВЫБРАТЬ
            |   Код,
            |   Наименование
            |ИЗ
            |   Справочник.Номенклатура";
        '''
        diags = _check(content, tmp_path, select={"BSL058"})
        assert "BSL058" in _codes(diags)

    def test_query_with_where_no_warning(self, tmp_path: Path) -> None:
        content = '''\
            ТекстЗапроса = "ВЫБРАТЬ
            |   Код
            |ИЗ
            |   Справочник.Номенклатура
            |ГДЕ
            |   Код = &Код";
        '''
        diags = _check(content, tmp_path, select={"BSL058"})
        assert "BSL058" not in _codes(diags)

    def test_query_with_first_no_warning(self, tmp_path: Path) -> None:
        content = '''\
            ТекстЗапроса = "ВЫБРАТЬ ПЕРВЫЕ 10
            |   Код
            |ИЗ
            |   Справочник.Номенклатура";
        '''
        diags = _check(content, tmp_path, select={"BSL058"})
        assert "BSL058" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL059 — BooleanLiteralComparison
# ---------------------------------------------------------------------------


class TestBsl059BooleanLiteralComparison:
    def test_comparison_with_true_detected(self, tmp_path: Path) -> None:
        content = "Если А = Истина Тогда\nКонецЕсли;\n"
        diags = _check(content, tmp_path, select={"BSL059"})
        assert "BSL059" in _codes(diags)

    def test_comparison_with_false_detected(self, tmp_path: Path) -> None:
        content = "Если Флаг = Ложь Тогда\nКонецЕсли;\n"
        diags = _check(content, tmp_path, select={"BSL059"})
        assert "BSL059" in _codes(diags)

    def test_plain_bool_no_warning(self, tmp_path: Path) -> None:
        content = "Если Флаг Тогда\nКонецЕсли;\n"
        diags = _check(content, tmp_path, select={"BSL059"})
        assert "BSL059" not in _codes(diags)

    def test_in_comment_no_warning(self, tmp_path: Path) -> None:
        content = "// Если А = Истина Тогда\n"
        diags = _check(content, tmp_path, select={"BSL059"})
        assert "BSL059" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL060 — DoubleNegation
# ---------------------------------------------------------------------------


class TestBsl060DoubleNegation:
    def test_double_negation_detected(self, tmp_path: Path) -> None:
        content = "Если НЕ НЕ Флаг Тогда\nКонецЕсли;\n"
        diags = _check(content, tmp_path, select={"BSL060"})
        assert "BSL060" in _codes(diags)

    def test_single_negation_no_warning(self, tmp_path: Path) -> None:
        content = "Если НЕ Флаг Тогда\nКонецЕсли;\n"
        diags = _check(content, tmp_path, select={"BSL060"})
        assert "BSL060" not in _codes(diags)

    def test_in_comment_no_warning(self, tmp_path: Path) -> None:
        content = "// НЕ НЕ Флаг\n"
        diags = _check(content, tmp_path, select={"BSL060"})
        assert "BSL060" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL061 — AbruptLoopExit
# ---------------------------------------------------------------------------


class TestBsl061AbruptLoopExit:
    def test_break_as_last_stmt_detected(self, tmp_path: Path) -> None:
        content = """\
            Для Каждого Элемент Из Список Цикл
                ОбработатьЭлемент(Элемент);
                Прервать;
            КонецЦикла;
        """
        diags = _check(content, tmp_path, select={"BSL061"})
        assert "BSL061" in _codes(diags)

    def test_break_in_middle_no_warning(self, tmp_path: Path) -> None:
        content = """\
            Для Каждого Элемент Из Список Цикл
                Если УсловиеВыхода(Элемент) Тогда
                    Прервать;
                КонецЕсли;
                ОбработатьЭлемент(Элемент);
            КонецЦикла;
        """
        diags = _check(content, tmp_path, select={"BSL061"})
        assert "BSL061" not in _codes(diags)


# ---------------------------------------------------------------------------
# Metadata completeness
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# BSL062 — UnusedParameter
# ---------------------------------------------------------------------------


class TestBsl062UnusedParameter:
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

    def test_underscore_param_ignored(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест(_НеИспользуемый)
                А = 1;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL062"})
        assert "BSL062" not in _codes(diags)

    def test_no_params_no_warning(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                А = 1;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL062"})
        assert "BSL062" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL063 — LargeModule
# ---------------------------------------------------------------------------


class TestBsl063LargeModule:
    def test_large_module_detected(self, tmp_path: Path) -> None:
        content = "\n".join([f"А{i} = {i};" for i in range(1100)]) + "\n"
        diags = _check(content, tmp_path, select={"BSL063"}, max_module_lines=1000)
        assert "BSL063" in _codes(diags)

    def test_small_module_no_warning(self, tmp_path: Path) -> None:
        content = "А = 1;\nБ = 2;\n"
        diags = _check(content, tmp_path, select={"BSL063"}, max_module_lines=1000)
        assert "BSL063" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL064 — ProcedureReturnsValue
# ---------------------------------------------------------------------------


class TestBsl064ProcedureReturnsValue:
    def test_procedure_with_return_value_detected(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Возврат 42;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL064"})
        assert "BSL064" in _codes(diags)

    def test_function_with_return_no_warning(self, tmp_path: Path) -> None:
        content = """\
            Функция Тест()
                Возврат 42;
            КонецФункции
        """
        diags = _check(content, tmp_path, select={"BSL064"})
        assert "BSL064" not in _codes(diags)

    def test_procedure_return_empty_no_warning(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Если Условие Тогда
                    Возврат;
                КонецЕсли;
                А = 1;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL064"})
        assert "BSL064" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL065 — MissingExportComment
# ---------------------------------------------------------------------------


class TestBsl065MissingExportComment:
    def test_export_without_comment_detected(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест() Экспорт
                А = 1;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL065"})
        assert "BSL065" in _codes(diags)

    def test_export_with_comment_no_warning(self, tmp_path: Path) -> None:
        content = """\
            // Описание метода
            Процедура Тест() Экспорт
                А = 1;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL065"})
        assert "BSL065" not in _codes(diags)

    def test_non_export_no_warning(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                А = 1;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL065"})
        assert "BSL065" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL066 — DeprecatedPlatformMethod
# ---------------------------------------------------------------------------


class TestBsl066DeprecatedPlatformMethod:
    def test_deprecated_message_detected(self, tmp_path: Path) -> None:
        content = 'Сообщить("Привет");\n'
        diags = _check(content, tmp_path, select={"BSL066"})
        assert "BSL066" in _codes(diags)

    def test_in_comment_no_warning(self, tmp_path: Path) -> None:
        content = '// Сообщить("Привет");\n'
        diags = _check(content, tmp_path, select={"BSL066"})
        assert "BSL066" not in _codes(diags)

    def test_modern_method_no_warning(self, tmp_path: Path) -> None:
        content = 'ПоказатьОповещение("Привет", , "Заголовок");\n'
        diags = _check(content, tmp_path, select={"BSL066"})
        assert "BSL066" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL067 — VarDeclarationAfterCode
# ---------------------------------------------------------------------------


class TestBsl067VarDeclarationAfterCode:
    def test_var_after_code_detected(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                А = 1;
                Перем Б;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL067"})
        assert "BSL067" in _codes(diags)

    def test_var_before_code_no_warning(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Перем Б;
                А = 1;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL067"})
        assert "BSL067" not in _codes(diags)

    def test_no_var_no_warning(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                А = 1;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL067"})
        assert "BSL067" not in _codes(diags)


class TestBsl068TooManyElseIf:
    def test_many_elseif_detected(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест(А)
    Если А = 1 Тогда
        Б = 1;
    ИначеЕсли А = 2 Тогда
        Б = 2;
    ИначеЕсли А = 3 Тогда
        Б = 3;
    ИначеЕсли А = 4 Тогда
        Б = 4;
    ИначеЕсли А = 5 Тогда
        Б = 5;
    ИначеЕсли А = 6 Тогда
        Б = 6;
    ИначеЕсли А = 7 Тогда
        Б = 7;
    КонецЕсли;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL068"})
        assert "BSL068" in _codes(diags)

    def test_few_elseif_no_warning(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест(А)
    Если А = 1 Тогда
        Б = 1;
    ИначеЕсли А = 2 Тогда
        Б = 2;
    КонецЕсли;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL068"})
        assert "BSL068" not in _codes(diags)

    def test_nested_if_not_counted(self, tmp_path: Path) -> None:
        """Inner ИначеЕсли branches should not count against outer Если."""
        content = """\
Процедура Тест(А)
    Если А = 1 Тогда
        Если А > 0 Тогда
            ИначеЕсли А > 1 Тогда
            ИначеЕсли А > 2 Тогда
            ИначеЕсли А > 3 Тогда
            ИначеЕсли А > 4 Тогда
            ИначеЕсли А > 5 Тогда
        КонецЕсли;
    КонецЕсли;
КонецПроцедуры
"""
        # Outer Если has 0 ИначеЕсли — should NOT trigger BSL068
        diags = _check(content, tmp_path, select={"BSL068"})
        # The outer Если has 0 ElsIf so no warning at its level
        outer_warnings = [d for d in diags if d.code == "BSL068" and d.line == 2]
        assert not outer_warnings


class TestBsl069InfiniteLoop:
    def test_while_true_without_break_detected(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    Пока Истина Цикл
        А = 1;
    КонецЦикла;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL069"})
        assert "BSL069" in _codes(diags)

    def test_while_true_with_break_ok(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    Пока Истина Цикл
        А = А + 1;
        Если А > 10 Тогда
            Прервать;
        КонецЕсли;
    КонецЦикла;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL069"})
        assert "BSL069" not in _codes(diags)

    def test_regular_while_loop_no_warning(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    Пока А < 10 Цикл
        А = А + 1;
    КонецЦикла;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL069"})
        assert "BSL069" not in _codes(diags)


class TestBsl070EmptyLoopBody:
    def test_empty_loop_detected(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    Для А = 1 По 10 Цикл
    КонецЦикла;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL070"})
        assert "BSL070" in _codes(diags)

    def test_comment_only_loop_detected(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    Для А = 1 По 10 Цикл
        // TODO: implement
    КонецЦикла;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL070"})
        assert "BSL070" in _codes(diags)

    def test_loop_with_body_no_warning(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    Для А = 1 По 10 Цикл
        Б = А * 2;
    КонецЦикла;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL070"})
        assert "BSL070" not in _codes(diags)


# ---------------------------------------------------------------------------
# Metadata completeness
# ---------------------------------------------------------------------------


class TestBsl071MagicNumber:
    def test_magic_number_in_method_detected(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    Если А > 42 Тогда
        Б = 1;
    КонецЕсли;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL071"})
        assert "BSL071" in _codes(diags)

    def test_common_numbers_not_flagged(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    А = 0;
    Б = 1;
    В = 2;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL071"})
        assert "BSL071" not in _codes(diags)

    def test_no_method_body_not_flagged(self, tmp_path: Path) -> None:
        content = "А = 42;\n"
        diags = _check(content, tmp_path, select={"BSL071"})
        assert "BSL071" not in _codes(diags)


class TestBsl072StringConcatInLoop:
    def test_concat_in_loop_detected(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    Для А = 1 По 10 Цикл
        Результат = Результат + "строка";
    КонецЦикла;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL072"})
        assert "BSL072" in _codes(diags)

    def test_concat_outside_loop_no_warning(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    Результат = Результат + "строка";
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL072"})
        assert "BSL072" not in _codes(diags)

    def test_numeric_add_in_loop_no_warning(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    Для А = 1 По 10 Цикл
        Сумма = Сумма + А;
    КонецЦикла;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL072"})
        assert "BSL072" not in _codes(diags)


class TestBsl073MissingElseBranch:
    def test_if_with_elseif_no_else_detected(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест(А)
    Если А = 1 Тогда
        Б = 1;
    ИначеЕсли А = 2 Тогда
        Б = 2;
    КонецЕсли;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL073"})
        assert "BSL073" in _codes(diags)

    def test_if_with_elseif_and_else_ok(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест(А)
    Если А = 1 Тогда
        Б = 1;
    ИначеЕсли А = 2 Тогда
        Б = 2;
    Иначе
        Б = 0;
    КонецЕсли;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL073"})
        assert "BSL073" not in _codes(diags)

    def test_simple_if_without_elseif_no_warning(self, tmp_path: Path) -> None:
        """Pure Если...Тогда...КонецЕсли without any ИначеЕсли is not flagged."""
        content = """\
Процедура Тест(А)
    Если А = 1 Тогда
        Б = 1;
    КонецЕсли;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL073"})
        assert "BSL073" not in _codes(diags)


class TestBsl074TodoComment:
    def test_todo_detected(self, tmp_path: Path) -> None:
        content = "// TODO: refactor this\nА = 1;\n"
        diags = _check(content, tmp_path, select={"BSL074"})
        assert "BSL074" in _codes(diags)

    def test_fixme_detected(self, tmp_path: Path) -> None:
        content = "// FIXME: broken edge case\nА = 1;\n"
        diags = _check(content, tmp_path, select={"BSL074"})
        assert "BSL074" in _codes(diags)

    def test_regular_comment_no_warning(self, tmp_path: Path) -> None:
        content = "// Обычный комментарий\nА = 1;\n"
        diags = _check(content, tmp_path, select={"BSL074"})
        assert "BSL074" not in _codes(diags)


class TestBsl075GlobalVariableModification:
    def test_module_var_modified_in_method(self, tmp_path: Path) -> None:
        content = """\
Перем Счётчик;

Процедура Увеличить()
    Счётчик = Счётчик + 1;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL075"})
        assert "BSL075" in _codes(diags)

    def test_local_param_assignment_no_warning(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест(Значение)
    Значение = Значение + 1;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL075"})
        assert "BSL075" not in _codes(diags)

    def test_no_module_vars_no_warning(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    А = 1;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL075"})
        assert "BSL075" not in _codes(diags)


class TestBsl076NegativeConditionFirst:
    def test_not_condition_detected(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест(А)
    Если НЕ А Тогда
        Б = 1;
    КонецЕсли;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL076"})
        assert "BSL076" in _codes(diags)

    def test_positive_condition_no_warning(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест(А)
    Если А Тогда
        Б = 1;
    КонецЕсли;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL076"})
        assert "BSL076" not in _codes(diags)

    def test_elseif_negative_detected(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест(А, Б)
    Если А Тогда
        В = 1;
    ИначеЕсли НЕ Б Тогда
        В = 2;
    КонецЕсли;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL076"})
        assert "BSL076" in _codes(diags)


class TestBsl077SelectStar:
    def test_select_star_detected(self, tmp_path: Path) -> None:
        content = 'А = "ВЫБРАТЬ * ИЗ Документ.РасходнаяНакладная";\n'
        diags = _check(content, tmp_path, select={"BSL077"})
        assert "BSL077" in _codes(diags)

    def test_select_columns_no_warning(self, tmp_path: Path) -> None:
        content = 'А = "ВЫБРАТЬ Ссылка, Номер ИЗ Документ.РасходнаяНакладная";\n'
        diags = _check(content, tmp_path, select={"BSL077"})
        assert "BSL077" not in _codes(diags)

    def test_english_select_star_detected(self, tmp_path: Path) -> None:
        content = 'А = "SELECT * FROM Document.Invoice";\n'
        diags = _check(content, tmp_path, select={"BSL077"})
        assert "BSL077" in _codes(diags)


class TestBsl078RaiseWithoutMessage:
    def test_bare_raise_detected(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    Попытка
        А = 1;
    Исключение
        ВызватьИсключение;
    КонецПопытки;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL078"})
        assert "BSL078" in _codes(diags)

    def test_raise_with_message_no_warning(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    Попытка
        А = 1;
    Исключение
        ВызватьИсключение "Ошибка операции";
    КонецПопытки;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL078"})
        assert "BSL078" not in _codes(diags)


class TestBsl079UsingGoto:
    def test_goto_detected(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    Перейти ~МетодМетки;
~МетодМетки:
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL079"})
        assert "BSL079" in _codes(diags)

    def test_no_goto_no_warning(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    А = 1;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL079"})
        assert "BSL079" not in _codes(diags)


class TestBsl080SilentCatch:
    def test_silent_catch_detected(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    Попытка
        А = 1 / 0;
    Исключение
        // ничего не делаем
    КонецПопытки;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL080"})
        assert "BSL080" in _codes(diags)

    def test_catch_with_error_info_ok(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    Попытка
        А = 1 / 0;
    Исключение
        Ошибка = ИнформацияОбОшибке();
        Сообщить(Ошибка.Описание);
    КонецПопытки;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL080"})
        assert "BSL080" not in _codes(diags)

    def test_catch_with_reraise_ok(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    Попытка
        А = 1 / 0;
    Исключение
        ВызватьИсключение;
    КонецПопытки;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL080"})
        assert "BSL080" not in _codes(diags)


class TestBsl081LongMethodChain:
    def test_long_chain_detected(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    Результат = А.Б().В().Г().Д().Е().Ж();
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL081"})
        assert "BSL081" in _codes(diags)

    def test_short_chain_no_warning(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    Результат = А.Б().В();
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL081"})
        assert "BSL081" not in _codes(diags)


class TestBsl082MissingNewlineAtEof:
    def test_missing_newline_detected(self, tmp_path: Path) -> None:
        p = tmp_path / "t.bsl"
        p.write_bytes("А = 1;".encode())  # no trailing newline
        from bsl_analyzer.analysis.diagnostics import DiagnosticEngine
        diags = DiagnosticEngine(select={"BSL082"}).check_file(str(p))
        assert any(d.code == "BSL082" for d in diags)

    def test_file_with_newline_ok(self, tmp_path: Path) -> None:
        content = "А = 1;\n"
        diags = _check(content, tmp_path, select={"BSL082"})
        assert "BSL082" not in _codes(diags)


class TestBsl083TooManyModuleVariables:
    def test_many_module_vars_detected(self, tmp_path: Path) -> None:
        vars_lines = "\n".join(f"Перем Переменная{i};" for i in range(12))
        content = vars_lines + "\nА = 1;\n"
        diags = _check(content, tmp_path, select={"BSL083"})
        assert "BSL083" in _codes(diags)

    def test_few_module_vars_no_warning(self, tmp_path: Path) -> None:
        content = "Перем А;\nПерем Б;\nА = 1;\n"
        diags = _check(content, tmp_path, select={"BSL083"})
        assert "BSL083" not in _codes(diags)


class TestBsl084FunctionWithNoReturn:
    def test_function_without_return_detected(self, tmp_path: Path) -> None:
        content = """\
Функция ВсегдаПусто()
    А = 1;
КонецФункции
"""
        diags = _check(content, tmp_path, select={"BSL084"})
        assert "BSL084" in _codes(diags)

    def test_function_with_return_ok(self, tmp_path: Path) -> None:
        content = """\
Функция Получить()
    Возврат 42;
КонецФункции
"""
        diags = _check(content, tmp_path, select={"BSL084"})
        assert "BSL084" not in _codes(diags)

    def test_procedure_not_flagged(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    А = 1;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL084"})
        assert "BSL084" not in _codes(diags)


class TestBsl085LiteralBooleanCondition:
    def test_if_true_detected(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    Если Истина Тогда
        А = 1;
    КонецЕсли;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL085"})
        assert "BSL085" in _codes(diags)

    def test_if_false_detected(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    Если Ложь Тогда
        А = 1;
    КонецЕсли;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL085"})
        assert "BSL085" in _codes(diags)

    def test_normal_condition_no_warning(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест(А)
    Если А > 0 Тогда
        Б = 1;
    КонецЕсли;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL085"})
        assert "BSL085" not in _codes(diags)


class TestBsl086HttpRequestInLoop:
    def test_http_in_loop_detected(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    Для А = 1 По 10 Цикл
        Соединение = Новый HTTPСоединение("example.com");
    КонецЦикла;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL086"})
        assert "BSL086" in _codes(diags)

    def test_http_outside_loop_no_warning(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    Соединение = Новый HTTPСоединение("example.com");
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL086"})
        assert "BSL086" not in _codes(diags)


class TestBsl087ObjectCreationInLoop:
    def test_new_object_in_loop_detected(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    Для А = 1 По 10 Цикл
        Запрос = Новый Запрос;
    КонецЦикла;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL087"})
        assert "BSL087" in _codes(diags)

    def test_allowed_new_in_loop_no_warning(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    Для А = 1 По 10 Цикл
        Стр = Новый Структура;
    КонецЦикла;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL087"})
        assert "BSL087" not in _codes(diags)


class TestBsl088MissingParameterComment:
    def test_export_with_params_no_comment_detected(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест(Значение) Экспорт
    А = Значение;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL088"})
        assert "BSL088" in _codes(diags)

    def test_export_with_params_and_comment_ok(self, tmp_path: Path) -> None:
        content = """\
// Процедура для теста.
// Параметры:
//   Значение — тестовое значение.
Процедура Тест(Значение) Экспорт
    А = Значение;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL088"})
        assert "BSL088" not in _codes(diags)

    def test_non_export_method_not_flagged(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест(Значение)
    А = Значение;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL088"})
        assert "BSL088" not in _codes(diags)


class TestBsl089TransactionInLoop:
    def test_transaction_in_loop_detected(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    Для А = 1 По 10 Цикл
        НачатьТранзакцию();
        ЗафиксироватьТранзакцию();
    КонецЦикла;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL089"})
        assert "BSL089" in _codes(diags)

    def test_transaction_outside_loop_no_warning(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    НачатьТранзакцию();
    А = 1;
    ЗафиксироватьТранзакцию();
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL089"})
        assert "BSL089" not in _codes(diags)


class TestBsl090HardcodedConnectionString:
    def test_dsn_detected(self, tmp_path: Path) -> None:
        content = 'Строка = "Server=myserver;Database=mydb;Uid=user;Pwd=pass";\n'
        diags = _check(content, tmp_path, select={"BSL090"})
        assert "BSL090" in _codes(diags)

    def test_no_connection_string_no_warning(self, tmp_path: Path) -> None:
        content = 'Строка = "Обычная строка без параметров подключения";\n'
        diags = _check(content, tmp_path, select={"BSL090"})
        assert "BSL090" not in _codes(diags)


class TestBsl091RedundantElseAfterReturn:
    def test_else_after_return_detected(self, tmp_path: Path) -> None:
        content = """\
Функция Тест(А)
    Если А > 0 Тогда
        Возврат Истина;
    Иначе
        Возврат Ложь;
    КонецЕсли;
КонецФункции
"""
        diags = _check(content, tmp_path, select={"BSL091"})
        assert "BSL091" in _codes(diags)

    def test_else_without_prior_return_no_warning(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест(А)
    Если А > 0 Тогда
        Б = 1;
    Иначе
        Б = 2;
    КонецЕсли;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL091"})
        assert "BSL091" not in _codes(diags)

    def test_no_else_no_warning(self, tmp_path: Path) -> None:
        content = """\
Функция Тест(А)
    Если А > 0 Тогда
        Возврат Истина;
    КонецЕсли;
    Возврат Ложь;
КонецФункции
"""
        diags = _check(content, tmp_path, select={"BSL091"})
        assert "BSL091" not in _codes(diags)


class TestBsl092EmptyElseBlock:
    def test_empty_else_detected(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест(А)
    Если А > 0 Тогда
        Б = 1;
    Иначе
    КонецЕсли;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL092"})
        assert "BSL092" in _codes(diags)

    def test_else_with_code_no_warning(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест(А)
    Если А > 0 Тогда
        Б = 1;
    Иначе
        Б = 0;
    КонецЕсли;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL092"})
        assert "BSL092" not in _codes(diags)


class TestBsl093ComparisonToNull:
    def test_null_comparison_detected(self, tmp_path: Path) -> None:
        content = 'Если А = NULL Тогда\n    Б = 1;\nКонецЕсли;\n'
        diags = _check(content, tmp_path, select={"BSL093"})
        assert "BSL093" in _codes(diags)

    def test_undefined_comparison_no_warning(self, tmp_path: Path) -> None:
        content = 'Если А = Неопределено Тогда\n    Б = 1;\nКонецЕсли;\n'
        diags = _check(content, tmp_path, select={"BSL093"})
        assert "BSL093" not in _codes(diags)


class TestBsl094NoopAssignment:
    def test_plus_zero_detected(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    А += 0;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL094"})
        assert "BSL094" in _codes(diags)

    def test_normal_increment_no_warning(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    А += 1;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL094"})
        assert "BSL094" not in _codes(diags)


class TestBsl095MultipleStatementsOnOneLine:
    def test_two_stmts_on_one_line_detected(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    А = 1; Б = 2;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL095"})
        assert "BSL095" in _codes(diags)

    def test_single_stmt_no_warning(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    А = 1;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL095"})
        assert "BSL095" not in _codes(diags)

    def test_comment_line_no_warning(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    // А = 1; Б = 2;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL095"})
        assert "BSL095" not in _codes(diags)


class TestBsl096UndocumentedExportMethod:
    def test_export_without_comment_detected(self, tmp_path: Path) -> None:
        content = """\
Процедура ОткрытьФорму() Экспорт
    А = 1;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL096"})
        assert "BSL096" in _codes(diags)

    def test_export_with_comment_no_warning(self, tmp_path: Path) -> None:
        content = """\
// Открывает форму
Процедура ОткрытьФорму() Экспорт
    А = 1;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL096"})
        assert "BSL096" not in _codes(diags)

    def test_non_export_no_warning(self, tmp_path: Path) -> None:
        content = """\
Процедура ВнутренняяПроцедура()
    А = 1;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL096"})
        assert "BSL096" not in _codes(diags)


class TestBsl097UseOfCurrentDate:
    def test_current_date_detected(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    Д = ТекущаяДата();
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL097"})
        assert "BSL097" in _codes(diags)

    def test_current_date_english_detected(self, tmp_path: Path) -> None:
        content = """\
Procedure Test()
    D = CurrentDate();
EndProcedure
"""
        diags = _check(content, tmp_path, select={"BSL097"})
        assert "BSL097" in _codes(diags)

    def test_session_date_no_warning(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    Д = ТекущаяДатаСеанса();
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL097"})
        assert "BSL097" not in _codes(diags)

    def test_comment_line_no_warning(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    // Д = ТекущаяДата();
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL097"})
        assert "BSL097" not in _codes(diags)


class TestBsl098UseOfExecute:
    def test_execute_detected(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    Выполнить("А = 1;");
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL098"})
        assert "BSL098" in _codes(diags)

    def test_comment_no_warning(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    // Выполнить("А = 1;");
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL098"})
        assert "BSL098" not in _codes(diags)

    def test_no_execute_no_warning(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    А = 1;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL098"})
        assert "BSL098" not in _codes(diags)


class TestBsl099TooManyParameters:
    def test_eight_params_detected(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест(А, Б, В, Г, Д, Е, Ж, З)
    А = 1;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL099"})
        assert "BSL099" in _codes(diags)

    def test_seven_params_no_warning(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест(А, Б, В, Г, Д, Е, Ж)
    А = 1;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL099"})
        assert "BSL099" not in _codes(diags)


class TestBsl100HardcodedFilePath:
    def test_windows_path_detected(self, tmp_path: Path) -> None:
        content = 'Путь = "C:\\Users\\test\\file.txt";\n'
        diags = _check(content, tmp_path, select={"BSL100"})
        assert "BSL100" in _codes(diags)

    def test_unix_path_detected(self, tmp_path: Path) -> None:
        content = 'Путь = "/home/user/file.txt";\n'
        diags = _check(content, tmp_path, select={"BSL100"})
        assert "BSL100" in _codes(diags)

    def test_relative_path_no_warning(self, tmp_path: Path) -> None:
        content = 'Путь = "documents/file.txt";\n'
        diags = _check(content, tmp_path, select={"BSL100"})
        assert "BSL100" not in _codes(diags)


class TestBsl101TooDeepNesting:
    def test_deep_nesting_detected(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    Если А Тогда
        Если Б Тогда
            Если В Тогда
                Если Г Тогда
                    Если Д Тогда
                        Если Е Тогда
                            Если Ж Тогда
                                Х = 1;
                            КонецЕсли;
                        КонецЕсли;
                    КонецЕсли;
                КонецЕсли;
            КонецЕсли;
        КонецЕсли;
    КонецЕсли;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL101"})
        assert "BSL101" in _codes(diags)

    def test_shallow_nesting_no_warning(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    Если А Тогда
        Если Б Тогда
            Х = 1;
        КонецЕсли;
    КонецЕсли;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL101"})
        assert "BSL101" not in _codes(diags)


class TestBsl102LargeModule:
    def test_large_module_detected(self, tmp_path: Path) -> None:
        lines = ["А = 1;\n"] * 501
        content = "".join(lines)
        diags = _check(content, tmp_path, select={"BSL102"})
        assert "BSL102" in _codes(diags)

    def test_small_module_no_warning(self, tmp_path: Path) -> None:
        content = "А = 1;\n"
        diags = _check(content, tmp_path, select={"BSL102"})
        assert "BSL102" not in _codes(diags)


class TestBsl103UseOfEval:
    def test_eval_detected(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    Рез = Вычислить("1 + 2");
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL103"})
        assert "BSL103" in _codes(diags)

    def test_comment_no_warning(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    // Рез = Вычислить("1 + 2");
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL103"})
        assert "BSL103" not in _codes(diags)


class TestBsl104MissingModuleComment:
    def test_no_comment_detected(self, tmp_path: Path) -> None:
        content = "А = 1;\n"
        diags = _check(content, tmp_path, select={"BSL104"})
        assert "BSL104" in _codes(diags)

    def test_comment_at_top_no_warning(self, tmp_path: Path) -> None:
        content = "// Описание модуля\nА = 1;\n"
        diags = _check(content, tmp_path, select={"BSL104"})
        assert "BSL104" not in _codes(diags)


class TestBsl105UseOfSleep:
    def test_sleep_detected(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    Приостановить(1000);
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL105"})
        assert "BSL105" in _codes(diags)

    def test_comment_no_warning(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    // Приостановить(1000);
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL105"})
        assert "BSL105" not in _codes(diags)


class TestBsl106QueryInLoop:
    def test_select_in_while_loop_detected(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    Пока Условие Цикл
        Запрос = "ВЫБРАТЬ * ИЗ Таблица";
    КонецЦикла;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL106"})
        assert "BSL106" in _codes(diags)

    def test_select_outside_loop_no_warning(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    Запрос = "ВЫБРАТЬ * ИЗ Таблица";
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL106"})
        assert "BSL106" not in _codes(diags)


class TestBsl107EmptyThenBranch:
    def test_empty_then_detected(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест(А)
    Если А > 0 Тогда
    КонецЕсли;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL107"})
        assert "BSL107" in _codes(diags)

    def test_then_with_code_no_warning(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест(А)
    Если А > 0 Тогда
        Б = 1;
    КонецЕсли;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL107"})
        assert "BSL107" not in _codes(diags)


class TestBsl108UseOfGlobalVariables:
    def test_exported_var_detected(self, tmp_path: Path) -> None:
        content = "Перем ГлобальнаяПеременная Экспорт;\n"
        diags = _check(content, tmp_path, select={"BSL108"})
        assert "BSL108" in _codes(diags)

    def test_non_exported_var_no_warning(self, tmp_path: Path) -> None:
        content = "Перем ЛокальнаяПеременная;\n"
        diags = _check(content, tmp_path, select={"BSL108"})
        assert "BSL108" not in _codes(diags)


class TestBsl109NegativeConditionalReturn:
    def test_not_condition_with_return_detected(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест(А)
    Если НЕ А > 0 Тогда
        Возврат;
    КонецЕсли;
    // основная логика
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL109"})
        assert "BSL109" in _codes(diags)

    def test_not_condition_without_return_no_warning(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест(А)
    Если НЕ А > 0 Тогда
        Б = 1;
    КонецЕсли;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL109"})
        assert "BSL109" not in _codes(diags)


class TestBsl110StringConcatInLoop:
    def test_concat_in_loop_detected(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    Пока Условие Цикл
        Строка = Строка + "часть";
    КонецЦикла;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL110"})
        assert "BSL110" in _codes(diags)

    def test_concat_outside_loop_no_warning(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    Строка = Строка + "часть";
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL110"})
        assert "BSL110" not in _codes(diags)


class TestBsl111MixedLanguageIdentifiers:
    def test_mixed_ident_detected(self, tmp_path: Path) -> None:
        content = "ИмяName = 1;\n"
        diags = _check(content, tmp_path, select={"BSL111"})
        assert "BSL111" in _codes(diags)

    def test_pure_cyrillic_no_warning(self, tmp_path: Path) -> None:
        content = "Имя = 1;\n"
        diags = _check(content, tmp_path, select={"BSL111"})
        assert "BSL111" not in _codes(diags)

    def test_pure_latin_no_warning(self, tmp_path: Path) -> None:
        content = "Name = 1;\n"
        diags = _check(content, tmp_path, select={"BSL111"})
        assert "BSL111" not in _codes(diags)


class TestBsl112UnterminatedTransaction:
    def test_begin_without_commit_detected(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    НачатьТранзакцию();
    А = 1;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL112"})
        assert "BSL112" in _codes(diags)

    def test_begin_with_commit_no_warning(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    НачатьТранзакцию();
    А = 1;
    ЗафиксироватьТранзакцию();
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL112"})
        assert "BSL112" not in _codes(diags)


class TestBsl113AssignmentInCondition:
    """BSL113 was removed: '=' in BSL conditions is always comparison, never assignment.
    BSL does not support assignment-expressions, so the rule had zero valid use cases."""

    def test_bsl113_never_triggers(self, tmp_path: Path) -> None:
        # '=' in Если is comparison — must NOT be flagged
        content = "Если А = Б Тогда\n    В = 1;\nКонецЕсли;\n"
        diags = _check(content, tmp_path, select={"BSL113"})
        assert "BSL113" not in _codes(diags)

    def test_parenthesised_condition_no_parse_error(self, tmp_path: Path) -> None:
        # tree-sitter-bsl grammar bug: Если (А = Б) was falsely flagged BSL001
        content = "Если (А = Б) Тогда\n    В = 1;\nКонецЕсли;\n"
        diags = _check(content, tmp_path)
        assert "BSL001" not in _codes(diags)


class TestBsl114EmptyModule:
    def test_only_comments_detected(self, tmp_path: Path) -> None:
        content = "// Просто комментарий\n"
        diags = _check(content, tmp_path, select={"BSL114"})
        assert "BSL114" in _codes(diags)

    def test_module_with_code_no_warning(self, tmp_path: Path) -> None:
        content = "А = 1;\n"
        diags = _check(content, tmp_path, select={"BSL114"})
        assert "BSL114" not in _codes(diags)


class TestBsl115ChainedNegation:
    def test_double_negation_detected(self, tmp_path: Path) -> None:
        content = "Если НЕ НЕ А Тогда\n    Б = 1;\nКонецЕсли;\n"
        diags = _check(content, tmp_path, select={"BSL115"})
        assert "BSL115" in _codes(diags)

    def test_single_negation_no_warning(self, tmp_path: Path) -> None:
        content = "Если НЕ А Тогда\n    Б = 1;\nКонецЕсли;\n"
        diags = _check(content, tmp_path, select={"BSL115"})
        assert "BSL115" not in _codes(diags)


class TestBsl116UseOfObsoleteIterator:
    def test_indexed_for_detected(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    Для И = 0 По 10 Цикл
        А = 1;
    КонецЦикла;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL116"})
        assert "BSL116" in _codes(diags)

    def test_foreach_no_warning(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    ДляКаждого Элемент Из Список Цикл
        А = 1;
    КонецЦикла;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL116"})
        assert "BSL116" not in _codes(diags)


class TestBsl117ProcedureCalledAsFunction:
    def test_proc_result_used_detected(self, tmp_path: Path) -> None:
        content = """\
Процедура ВыполнитьДействие()
КонецПроцедуры

Процедура Тест()
    Рез = ВыполнитьДействие();
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL117"})
        assert "BSL117" in _codes(diags)

    def test_function_result_used_no_warning(self, tmp_path: Path) -> None:
        content = """\
Функция ПолучитьЗначение()
    Возврат 42;
КонецФункции

Процедура Тест()
    Рез = ПолучитьЗначение();
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL117"})
        assert "BSL117" not in _codes(diags)


class TestBsl118FunctionReturnsNothing:
    def test_function_without_return_value_detected(self, tmp_path: Path) -> None:
        content = """\
Функция ПустаяФункция()
    А = 1;
КонецФункции
"""
        diags = _check(content, tmp_path, select={"BSL118"})
        assert "BSL118" in _codes(diags)

    def test_function_with_return_value_no_warning(self, tmp_path: Path) -> None:
        content = """\
Функция ПолучитьЗначение()
    Возврат 42;
КонецФункции
"""
        diags = _check(content, tmp_path, select={"BSL118"})
        assert "BSL118" not in _codes(diags)


class TestBsl119LineTooLong:
    def test_long_line_detected(self, tmp_path: Path) -> None:
        content = "А = " + '"' + "х" * 120 + '"' + ";\n"
        diags = _check(content, tmp_path, select={"BSL119"})
        assert "BSL119" in _codes(diags)

    def test_short_line_no_warning(self, tmp_path: Path) -> None:
        content = "А = 1;\n"
        diags = _check(content, tmp_path, select={"BSL119"})
        assert "BSL119" not in _codes(diags)


class TestBsl120TrailingWhitespace:
    def test_trailing_spaces_detected(self, tmp_path: Path) -> None:
        content = "А = 1;   \n"
        diags = _check(content, tmp_path, select={"BSL120"})
        assert "BSL120" in _codes(diags)

    def test_no_trailing_spaces_no_warning(self, tmp_path: Path) -> None:
        content = "А = 1;\n"
        diags = _check(content, tmp_path, select={"BSL120"})
        assert "BSL120" not in _codes(diags)


class TestBsl121TabIndentation:
    def test_tab_detected(self, tmp_path: Path) -> None:
        # Write directly — textwrap.dedent strips common leading whitespace
        p = tmp_path / "test.bsl"
        p.write_bytes("Процедура Тест()\n\tА = 1;\nКонецПроцедуры\n".encode())
        from bsl_analyzer.analysis.diagnostics import DiagnosticEngine
        diags = DiagnosticEngine(select={"BSL121"}).check_file(str(p))
        assert "BSL121" in _codes(diags)

    def test_spaces_no_warning(self, tmp_path: Path) -> None:
        content = "Процедура Тест()\n    А = 1;\nКонецПроцедуры\n"
        diags = _check(content, tmp_path, select={"BSL121"})
        assert "BSL121" not in _codes(diags)


class TestBsl122UnusedParameter:
    def test_unused_param_detected(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест(НеИспользуется)
    А = 1;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL122"})
        assert "BSL122" in _codes(diags)

    def test_used_param_no_warning(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест(Значение)
    А = Значение;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL122"})
        assert "BSL122" not in _codes(diags)


class TestBsl123CommentedOutCode:
    def test_commented_code_detected(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    // А = 1;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL123"})
        assert "BSL123" in _codes(diags)

    def test_plain_comment_no_warning(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    // Это просто комментарий
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL123"})
        assert "BSL123" not in _codes(diags)


class TestBsl124ShortProcedureName:
    def test_two_char_name_detected(self, tmp_path: Path) -> None:
        content = """\
Процедура ВП()
    А = 1;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL124"})
        assert "BSL124" in _codes(diags)

    def test_long_name_no_warning(self, tmp_path: Path) -> None:
        content = """\
Процедура ВыполнитьДействие()
    А = 1;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL124"})
        assert "BSL124" not in _codes(diags)


class TestBsl125BreakOutsideLoop:
    def test_break_outside_loop_detected(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    Прервать;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL125"})
        assert "BSL125" in _codes(diags)

    def test_break_inside_loop_no_warning(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    Пока Истина Цикл
        Прервать;
    КонецЦикла;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL125"})
        assert "BSL125" not in _codes(diags)


class TestBsl126ContinueOutsideLoop:
    def test_continue_outside_loop_detected(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    Продолжить;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL126"})
        assert "BSL126" in _codes(diags)

    def test_continue_inside_loop_no_warning(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    Пока Истина Цикл
        Продолжить;
    КонецЦикла;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL126"})
        assert "BSL126" not in _codes(diags)


class TestBsl127MultipleReturnValues:
    def test_multiple_top_level_returns_detected(self, tmp_path: Path) -> None:
        content = """\
Функция Тест(А)
    Если А > 0 Тогда
        Возврат 1;
    КонецЕсли;
    Возврат 0;
    Возврат -1;
КонецФункции
"""
        diags = _check(content, tmp_path, select={"BSL127"})
        assert "BSL127" in _codes(diags)

    def test_single_return_no_warning(self, tmp_path: Path) -> None:
        content = """\
Функция Тест(А)
    Если А > 0 Тогда
        Возврат 1;
    КонецЕсли;
    Возврат 0;
КонецФункции
"""
        diags = _check(content, tmp_path, select={"BSL127"})
        assert "BSL127" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL128 — DeadCodeAfterReturn
# ---------------------------------------------------------------------------


class TestBsl128DeadCodeAfterReturn:
    def test_dead_code_detected(self, tmp_path: Path) -> None:
        content = """\
Функция Тест()
    Возврат 1;
    А = 2;
КонецФункции
"""
        diags = _check(content, tmp_path, select={"BSL128"})
        assert "BSL128" in _codes(diags)

    def test_return_inside_if_no_warning(self, tmp_path: Path) -> None:
        content = """\
Функция Тест(А)
    Если А Тогда
        Возврат 1;
    КонецЕсли;
    Возврат 0;
КонецФункции
"""
        diags = _check(content, tmp_path, select={"BSL128"})
        assert "BSL128" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL129 — RecursiveCall
# ---------------------------------------------------------------------------


class TestBsl129RecursiveCall:
    def test_recursive_call_detected(self, tmp_path: Path) -> None:
        content = """\
Функция Факториал(Н)
    Возврат Факториал(Н - 1);
КонецФункции
"""
        diags = _check(content, tmp_path, select={"BSL129"})
        assert "BSL129" in _codes(diags)

    def test_no_self_call_no_warning(self, tmp_path: Path) -> None:
        content = """\
Функция Тест()
    Возврат 1;
КонецФункции
"""
        diags = _check(content, tmp_path, select={"BSL129"})
        assert "BSL129" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL130 — LongCommentLine
# ---------------------------------------------------------------------------


class TestBsl130LongCommentLine:
    def test_long_comment_detected(self, tmp_path: Path) -> None:
        long_comment = "// " + "x" * 120 + "\n"
        p = tmp_path / "test.bsl"
        p.write_text(long_comment, encoding="utf-8")
        from bsl_analyzer.analysis.diagnostics import DiagnosticEngine
        diags = DiagnosticEngine(select={"BSL130"}).check_file(str(p))
        assert "BSL130" in [d.code for d in diags]

    def test_short_comment_no_warning(self, tmp_path: Path) -> None:
        content = "// короткий комментарий\n"
        p = tmp_path / "test.bsl"
        p.write_text(content, encoding="utf-8")
        from bsl_analyzer.analysis.diagnostics import DiagnosticEngine
        diags = DiagnosticEngine(select={"BSL130"}).check_file(str(p))
        assert "BSL130" not in [d.code for d in diags]


# ---------------------------------------------------------------------------
# BSL131 — EmptyRegion
# ---------------------------------------------------------------------------


class TestBsl131EmptyRegion:
    def test_empty_region_detected(self, tmp_path: Path) -> None:
        content = "#Область ПустаяОбласть\n#КонецОбласти\n"
        p = tmp_path / "test.bsl"
        p.write_text(content, encoding="utf-8")
        from bsl_analyzer.analysis.diagnostics import DiagnosticEngine
        diags = DiagnosticEngine(select={"BSL131"}).check_file(str(p))
        assert "BSL131" in [d.code for d in diags]

    def test_region_with_code_no_warning(self, tmp_path: Path) -> None:
        content = "#Область СОдержимым\nА = 1;\n#КонецОбласти\n"
        p = tmp_path / "test.bsl"
        p.write_text(content, encoding="utf-8")
        from bsl_analyzer.analysis.diagnostics import DiagnosticEngine
        diags = DiagnosticEngine(select={"BSL131"}).check_file(str(p))
        assert "BSL131" not in [d.code for d in diags]


# ---------------------------------------------------------------------------
# BSL132 — RepeatedStringLiteral
# ---------------------------------------------------------------------------


class TestBsl132RepeatedStringLiteral:
    def test_repeated_4_times_detected(self, tmp_path: Path) -> None:
        content = (
            'А = "ТаблицаЗначений";\n'
            'Б = "ТаблицаЗначений";\n'
            'В = "ТаблицаЗначений";\n'
            'Г = "ТаблицаЗначений";\n'
        )
        p = tmp_path / "test.bsl"
        p.write_text(content, encoding="utf-8")
        from bsl_analyzer.analysis.diagnostics import DiagnosticEngine
        diags = DiagnosticEngine(select={"BSL132"}).check_file(str(p))
        assert "BSL132" in [d.code for d in diags]

    def test_repeated_3_times_no_warning(self, tmp_path: Path) -> None:
        content = (
            'А = "ТаблицаЗначений";\n'
            'Б = "ТаблицаЗначений";\n'
            'В = "ТаблицаЗначений";\n'
        )
        p = tmp_path / "test.bsl"
        p.write_text(content, encoding="utf-8")
        from bsl_analyzer.analysis.diagnostics import DiagnosticEngine
        diags = DiagnosticEngine(select={"BSL132"}).check_file(str(p))
        assert "BSL132" not in [d.code for d in diags]


# ---------------------------------------------------------------------------
# BSL133 — RequiredParamAfterOptional
# ---------------------------------------------------------------------------


class TestBsl133RequiredParamAfterOptional:
    def test_required_after_optional_detected(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест(Обязательный, Опциональный = 0, ЕщёОбязательный)
    А = 1;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL133"})
        assert "BSL133" in _codes(diags)

    def test_required_before_optional_no_warning(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест(Обязательный, ЕщёОбязательный, Опциональный = 0)
    А = 1;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL133"})
        assert "BSL133" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL134 — CyclomaticComplexity
# ---------------------------------------------------------------------------


class TestBsl134CyclomaticComplexity:
    def test_high_complexity_detected(self, tmp_path: Path) -> None:
        # 11 Если blocks → CC = 12 > 10
        ifs = "\n".join(
            f"    Если А{i} Тогда\n        Б = {i};\n    КонецЕсли;"
            for i in range(11)
        )
        content = f"Функция Тест()\n{ifs}\n    Возврат 0;\nКонецФункции\n"
        p = tmp_path / "test.bsl"
        p.write_text(content, encoding="utf-8")
        from bsl_analyzer.analysis.diagnostics import DiagnosticEngine
        diags = DiagnosticEngine(select={"BSL134"}).check_file(str(p))
        assert "BSL134" in [d.code for d in diags]

    def test_low_complexity_no_warning(self, tmp_path: Path) -> None:
        content = """\
Функция Тест()
    Если А Тогда
        Б = 1;
    КонецЕсли;
    Если В Тогда
        Г = 2;
    КонецЕсли;
    Если Д Тогда
        Е = 3;
    КонецЕсли;
    Возврат 0;
КонецФункции
"""
        diags = _check(content, tmp_path, select={"BSL134"})
        assert "BSL134" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL135 — NestedFunctionCalls
# ---------------------------------------------------------------------------


class TestBsl135NestedFunctionCalls:
    def test_nested_call_detected(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    Результат = Строка(Число(Переменная));
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL135"})
        assert "BSL135" in _codes(diags)

    def test_simple_call_no_warning(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    Результат = Строка(Переменная);
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL135"})
        assert "BSL135" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL136 — MissingSpaceBeforeComment
# ---------------------------------------------------------------------------


class TestBsl136MissingSpaceBeforeComment:
    def test_no_space_detected(self, tmp_path: Path) -> None:
        content = "А = 1;// комментарий\n"
        p = tmp_path / "test.bsl"
        p.write_text(content, encoding="utf-8")
        from bsl_analyzer.analysis.diagnostics import DiagnosticEngine
        diags = DiagnosticEngine(select={"BSL136"}).check_file(str(p))
        assert "BSL136" in [d.code for d in diags]

    def test_space_present_no_warning(self, tmp_path: Path) -> None:
        content = "А = 1; // комментарий\n"
        p = tmp_path / "test.bsl"
        p.write_text(content, encoding="utf-8")
        from bsl_analyzer.analysis.diagnostics import DiagnosticEngine
        diags = DiagnosticEngine(select={"BSL136"}).check_file(str(p))
        assert "BSL136" not in [d.code for d in diags]


# ---------------------------------------------------------------------------
# BSL137 — UseOfFindByDescription
# ---------------------------------------------------------------------------


class TestBsl137UseOfFindByDescription:
    def test_find_by_description_detected(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    Элемент = Справочники.Номенклатура.НайтиПоНаименованию("Товар");
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL137"})
        assert "BSL137" in _codes(diags)

    def test_find_by_ref_no_warning(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    Элемент = Справочники.Номенклатура.НайтиПоСсылке(Ссылка);
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL137"})
        assert "BSL137" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL138 — UseOfDebugOutput
# ---------------------------------------------------------------------------


class TestBsl138UseOfDebugOutput:
    def test_сообщить_detected(self, tmp_path: Path) -> None:
        content = 'Сообщить("отладка");\n'
        diags = _check(content, tmp_path, select={"BSL138"})
        assert "BSL138" in _codes(diags)

    def test_message_detected(self, tmp_path: Path) -> None:
        content = 'Message("debug");\n'
        diags = _check(content, tmp_path, select={"BSL138"})
        assert "BSL138" in _codes(diags)

    def test_no_debug_no_warning(self, tmp_path: Path) -> None:
        content = "А = 1;\n"
        diags = _check(content, tmp_path, select={"BSL138"})
        assert "BSL138" not in _codes(diags)

    def test_comment_skipped(self, tmp_path: Path) -> None:
        content = '// Сообщить("отладка");\n'
        diags = _check(content, tmp_path, select={"BSL138"})
        assert "BSL138" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL139 — TooLongParameterName
# ---------------------------------------------------------------------------


class TestBsl139TooLongParameterName:
    def test_long_param_detected(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест(ОченьДлинноеИмяПараметраКотороеПревышаетТридцатьСимволов)
    А = 1;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL139"})
        assert "BSL139" in _codes(diags)

    def test_short_param_no_warning(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест(ТипичноеИмяПараметра)
    А = 1;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL139"})
        assert "BSL139" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL140 — UnreachableElseIf
# ---------------------------------------------------------------------------


class TestBsl140UnreachableElseIf:
    def test_elseif_after_else_detected(self, tmp_path: Path) -> None:
        content = """\
Если А Тогда
    Б = 1;
Иначе
    В = 2;
ИначеЕсли Г Тогда
    Д = 3;
КонецЕсли;
"""
        diags = _check(content, tmp_path, select={"BSL140"})
        assert "BSL140" in _codes(diags)

    def test_normal_elseif_no_warning(self, tmp_path: Path) -> None:
        content = """\
Если А Тогда
    Б = 1;
ИначеЕсли В Тогда
    Г = 2;
КонецЕсли;
"""
        diags = _check(content, tmp_path, select={"BSL140"})
        assert "BSL140" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL141 — MagicBooleanReturn
# ---------------------------------------------------------------------------


class TestBsl141MagicBooleanReturn:
    def test_boolean_return_detected(self, tmp_path: Path) -> None:
        content = """\
Функция Тест(А)
    Если А Тогда
        Возврат Истина;
    КонецЕсли;
    Возврат Ложь;
КонецФункции
"""
        diags = _check(content, tmp_path, select={"BSL141"})
        assert "BSL141" in _codes(diags)

    def test_direct_return_no_warning(self, tmp_path: Path) -> None:
        content = """\
Функция Тест(А)
    Возврат А > 0;
КонецФункции
"""
        diags = _check(content, tmp_path, select={"BSL141"})
        assert "BSL141" not in _codes(diags)

    def test_only_true_return_no_warning(self, tmp_path: Path) -> None:
        content = """\
Функция Тест(А)
    Возврат Истина;
КонецФункции
"""
        diags = _check(content, tmp_path, select={"BSL141"})
        assert "BSL141" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL142 — LargeParameterDefaultValue
# ---------------------------------------------------------------------------


class TestBsl142LargeParameterDefaultValue:
    def test_large_default_detected(self, tmp_path: Path) -> None:
        content = (
            'Процедура Тест(Параметр = "Очень длинное значение по умолчанию которое превышает пятьдесят символов!")\n'
            "КонецПроцедуры\n"
        )
        diags = _check(content, tmp_path, select={"BSL142"})
        assert "BSL142" in _codes(diags)

    def test_short_default_no_warning(self, tmp_path: Path) -> None:
        content = "Процедура Тест(Параметр = 0)\nКонецПроцедуры\n"
        diags = _check(content, tmp_path, select={"BSL142"})
        assert "BSL142" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL143 — DuplicateElseIfCondition
# ---------------------------------------------------------------------------


class TestBsl143DuplicateElseIfCondition:
    def test_duplicate_condition_detected(self, tmp_path: Path) -> None:
        content = """\
Если А = 1 Тогда
    Б = 1;
ИначеЕсли А = 1 Тогда
    В = 2;
КонецЕсли;
"""
        diags = _check(content, tmp_path, select={"BSL143"})
        assert "BSL143" in _codes(diags)

    def test_different_conditions_no_warning(self, tmp_path: Path) -> None:
        content = """\
Если А = 1 Тогда
    Б = 1;
ИначеЕсли А = 2 Тогда
    В = 2;
КонецЕсли;
"""
        diags = _check(content, tmp_path, select={"BSL143"})
        assert "BSL143" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL144 — UnnecessaryParentheses
# ---------------------------------------------------------------------------


class TestBsl144UnnecessaryParentheses:
    def test_return_paren_detected(self, tmp_path: Path) -> None:
        content = """\
Функция Тест()
    Возврат (А + Б);
КонецФункции
"""
        diags = _check(content, tmp_path, select={"BSL144"})
        assert "BSL144" in _codes(diags)

    def test_return_no_paren_no_warning(self, tmp_path: Path) -> None:
        content = """\
Функция Тест()
    Возврат А + Б;
КонецФункции
"""
        diags = _check(content, tmp_path, select={"BSL144"})
        assert "BSL144" not in _codes(diags)

    def test_return_new_no_warning(self, tmp_path: Path) -> None:
        content = """\
Функция Тест()
    Возврат (Новый Массив());
КонецФункции
"""
        diags = _check(content, tmp_path, select={"BSL144"})
        assert "BSL144" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL145 — StringFormatInsteadOfConcat
# ---------------------------------------------------------------------------


class TestBsl145StringFormatInsteadOfConcat:
    def test_multi_concat_detected(self, tmp_path: Path) -> None:
        content = 'С = "Привет, " + Имя + "! Ваш код: " + Код + ".";\n'
        diags = _check(content, tmp_path, select={"BSL145"})
        assert "BSL145" in _codes(diags)

    def test_simple_concat_no_warning(self, tmp_path: Path) -> None:
        content = 'С = "Привет, " + Имя;\n'
        diags = _check(content, tmp_path, select={"BSL145"})
        assert "BSL145" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL146 — ModuleInitializationCode
# ---------------------------------------------------------------------------


class TestBsl146ModuleInitializationCode:
    def test_module_level_code_detected(self, tmp_path: Path) -> None:
        content = """\
А = 1;
ЗаполнитьТаблицу();
"""
        diags = _check(content, tmp_path, select={"BSL146"})
        assert "BSL146" in _codes(diags)

    def test_code_inside_proc_no_warning(self, tmp_path: Path) -> None:
        content = """\
Процедура Тест()
    А = 1;
КонецПроцедуры
"""
        diags = _check(content, tmp_path, select={"BSL146"})
        assert "BSL146" not in _codes(diags)

    def test_perем_declaration_no_warning(self, tmp_path: Path) -> None:
        content = "Перем МодульнаяПеременная;\n"
        diags = _check(content, tmp_path, select={"BSL146"})
        assert "BSL146" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL147 — UseOfUICall
# ---------------------------------------------------------------------------


class TestBsl147UseOfUICall:
    def test_open_form_detected(self, tmp_path: Path) -> None:
        content = 'ОткрытьФорму("ФормаТовара");\n'
        diags = _check(content, tmp_path, select={"BSL147"})
        assert "BSL147" in _codes(diags)

    def test_openform_english_detected(self, tmp_path: Path) -> None:
        content = 'OpenForm("ItemForm");\n'
        diags = _check(content, tmp_path, select={"BSL147"})
        assert "BSL147" in _codes(diags)

    def test_unrelated_call_no_warning(self, tmp_path: Path) -> None:
        content = "ПолучитьЗначение();\n"
        diags = _check(content, tmp_path, select={"BSL147"})
        assert "BSL147" not in _codes(diags)


class TestRuleMetadataCompleteness:
    def test_all_rules_in_metadata(self) -> None:
        from bsl_analyzer.analysis.diagnostics import RULE_METADATA
        expected = {f"BSL{i:03d}" for i in range(1, 148)}
        missing = expected - set(RULE_METADATA.keys())
        assert not missing, f"Missing RULE_METADATA entries: {missing}"
