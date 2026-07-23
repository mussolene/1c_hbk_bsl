"""Heavy and process-sharded diagnostics."""

from __future__ import annotations

from pathlib import Path

import pytest

from onec_hbk_bsl.analysis.diagnostics import (
    DiagnosticEngine,
)
from tests.diagnostic_test_support import _check, _codes, _rule_msg

pytestmark = [pytest.mark.performance, pytest.mark.slow]


# BSL208, BSL256 — TestBsl208Bsl256MixedScriptVsTypo
class TestBsl208Bsl256MixedScriptVsTypo:
    def test_homoglyph_identifier_reports_bsl208(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                \u0441onnection = 1;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL208", "BSL256"})
        assert "BSL208" in _codes(diags)

    def test_intentional_mixed_script_reports_bsl208(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                ИмяNameПользователь = 1;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL208", "BSL256"})
        assert "BSL208" in _codes(diags)
        assert "BSL256" not in _codes(diags)

    def test_bsl208_only_select_keeps_mixed_script_homoglyph_line(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                \u0441onnection = 1;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL208"})
        assert "BSL208" in _codes(diags)

    def test_platform_tech_names_not_flagged(self, tmp_path: Path) -> None:
        """Standard 1C platform API names with Latin tech acronyms are not BSL208."""
        content = """\
            Процедура Тест()
                Запрос = Новый HTTPЗапрос("/api");
                Данные = ЗначениеВJSON(Структура);
                Читатель = Новый XMLЧтение();
                Архив = Новый ЧтениеZIP(ПутьКАрхиву);
                Объект = Новый COMОбъект("ADODB.Connection");
                ТипJSON = JSONТип;
                НовыйSQL = "SELECT 1";
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL208", "BSL256"})
        assert "BSL208" not in _codes(diags)

    def test_additional_platform_tech_names_not_flagged(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Значение = Base64Значение;
                Подпись = PKCS7Подпись;
                CNs = CNsДоверенныхСтороннихУЦ(Данные);
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL208"})
        assert "BSL208" not in _codes(diags)

    def test_underscore_separated_latin_words_are_not_mixed_script(self, tmp_path: Path) -> None:
        content = """\
            Процедура Заполнить_AcceptanceCertificateBuyerContent(Контент)
                Свойства_AcceptanceCertificate = Контент.Свойства();
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL208"})
        assert "BSL208" not in _codes(diags)

    def test_underscore_separated_versioned_latin_words_match_bslls(self, tmp_path: Path) -> None:
        content = """\
            Процедура Заполнить_AddressInfo970(Контент)
                TaxRate_ЭтоЗначение_0 = Истина;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL208"})
        assert len([diag for diag in diags if diag.code == "BSL208"]) == 2

    def test_underscore_separated_short_numeric_latin_suffix_is_clean(self, tmp_path: Path) -> None:
        content = """\
            Процедура Заполнить_ProformaInvoice29(Контент)
                Возврат;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL208"})
        assert "BSL208" not in _codes(diags)

    def test_underscore_separated_tech_acronyms_match_bslls(self, tmp_path: Path) -> None:
        content = """\
            Функция XML_В_ОбъектXDTO(ДокументXML)
                XML_В_XDTO = ДокументXML;
                Возврат ДокументXML;
            КонецФункции
        """
        diags = _check(content, tmp_path, select={"BSL208"})
        assert len([diag for diag in diags if diag.code == "BSL208"]) == 2

    def test_underscore_separated_tech_acronym_prefix_is_clean(self, tmp_path: Path) -> None:
        content = """\
            Функция XML_КодЕдиницыИзмерения(КодЕдиницыИзмерения)
                Возврат КодЕдиницыИзмерения;
            КонецФункции
        """
        diags = _check(content, tmp_path, select={"BSL208"})
        assert "BSL208" not in _codes(diags)

    def test_homoglyphs_with_cyrillic_ve_and_en_report_bsl208(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                \u0412arcode = 1;
                \u041dTTPClient = 2;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL208", "BSL256"})
        assert "BSL208" in _codes(diags)

    def test_non_acronym_mixed_name_still_flagged(self, tmp_path: Path) -> None:
        """User-defined mixed-script names that don't use tech acronyms are still flagged."""
        content = """\
            Процедура Тест()
                ИмяName = 1;
                userIDПользователь = 2;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL208"})
        assert "BSL208" in _codes(diags)

    def test_call_before_declaration_reports_declaration_only(self, tmp_path: Path) -> None:
        content = """\
            Функция Обертка()
                Возврат МетодPUTОтвет();
            КонецФункции

            Функция МетодPUTОтвет()
                Возврат 1;
            КонецФункции
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL208"}) if d.code == "BSL208"]
        assert len(diags) == 1
        assert diags[0].line == 5

    def test_member_and_call_references_not_flagged(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Если ЗначениеЗаполнено(Результат.АдресS3) Тогда
                    Объект.ПолучитьДвоичныеДанныеИзS3();
                КонецЕсли;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL208"})
        assert "BSL208" not in _codes(diags)

    def test_cyrillic_property_after_dot_is_not_latin(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Объект.П = 1;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL208", "BSL256"})
        assert "BSL208" not in _codes(diags)

    def test_bslls_typo_sample_with_mocked_spellchecker(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """BSLLS TypoDiagnostic.bsl — string-literal typos only."""
        monkeypatch.setattr(
            "onec_hbk_bsl.analysis.bslls_typo.default_spell_fn",
            lambda word: word in {"Варинаты", "Атмена", "ыть"},
        )
        content = (
            "Функция Тест()\n"
            '\tСообщить("Атмена"); // Срабатывание здесь\n'
            "\tВозврат;\n"
            "КонецФункции\n"
            "\n"
            "Функция ВаринатыОплаты() // срабатывание здесь\n"
            "\tТипЗнч(Ссылка); // нет срабатывания\n"
            "\tВозврат;\n"
            '\tСообщить("ыть"); // срабатывание здесь\n'
            '\tДеньНедели = Формат(ДатаКолонки, "ДФ=ддд"); // Нет срабатывания\n'
            "\tЗапроситьДанныеОКВЭДФССВТранзакции = Истина; // Нет срабатывания\n"
            "КонецФункции\n"
        )
        path = tmp_path / "TypoSample.bsl"
        path.write_text(content, encoding="utf-8")
        diags = DiagnosticEngine(select={"BSL256"}).check_file(str(path))
        bsl256 = [d for d in diags if d.code == "BSL256"]
        assert len(bsl256) == 2
        assert {d.line for d in bsl256} == {2, 9}

    def test_bslls_typo_anchors_inside_string_fragment(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(
            "onec_hbk_bsl.analysis.bslls_typo.default_spell_fn",
            lambda word: word == "Атмена",
        )
        content = 'Процедура Тест()\n    Сообщить("Ошибка Атмена");\nКонецПроцедуры\n'
        path = tmp_path / "TypoStringAnchor.bsl"
        path.write_text(content, encoding="utf-8")

        diags = DiagnosticEngine(select={"BSL256"}).check_file(str(path))
        bsl256 = [d for d in diags if d.code == "BSL256"]
        assert len(bsl256) == 1
        line = content.splitlines()[1]
        start = line.index('"')
        assert bsl256[0].line == 2
        assert bsl256[0].character == start
        assert bsl256[0].end_character == line.rindex('"') + 1

    def test_bslls_typo_does_not_scan_non_assignment_identifiers(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            "onec_hbk_bsl.analysis.bslls_typo.default_spell_fn",
            lambda word: word == "Варинаты",
        )
        content = "Функция ПрефиксВаринатыОплаты()\n    Возврат 0;\nКонецФункции\n"
        path = tmp_path / "TypoIdentifierAnchor.bsl"
        path.write_text(content, encoding="utf-8")

        diags = DiagnosticEngine(select={"BSL256"}).check_file(str(path))
        bsl256 = [d for d in diags if d.code == "BSL256"]
        assert not bsl256

    def test_bslls_typo_scans_assignment_identifier_selectively(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "onec_hbk_bsl.analysis.bslls_typo.default_spell_fn",
            lambda word: word == "Поздниее",
        )
        content = "Процедура Тест()\n    НаиболееПоздниееПодтверждение = 1;\nКонецПроцедуры\n"
        path = tmp_path / "TypoIdentifierLhs.bsl"
        path.write_text(content, encoding="utf-8")

        diags = [
            d
            for d in DiagnosticEngine(select={"BSL256"}).check_file(str(path))
            if d.code == "BSL256"
        ]
        assert len(diags) == 1
        assert diags[0].line == 2
        assert diags[0].message == _rule_msg("BSL256")

    def test_bslls_typo_scans_assignment_property_selectively(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "onec_hbk_bsl.analysis.bslls_typo.default_spell_fn",
            lambda word: word == "Поздниее",
        )
        content = "Процедура Тест()\n    Объект.ПоздниееПодтверждение = 1;\nКонецПроцедуры\n"
        path = tmp_path / "TypoPropertyLhs.bsl"
        path.write_text(content, encoding="utf-8")

        diags = [
            d
            for d in DiagnosticEngine(select={"BSL256"}).check_file(str(path))
            if d.code == "BSL256"
        ]
        assert len(diags) == 1
        assert diags[0].line == 2
        assert diags[0].message == _rule_msg("BSL256")

    def test_bslls_typo_forces_reference_fragment_and_reports_next(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            "onec_hbk_bsl.analysis.bslls_typo.default_spell_fn",
            lambda word: word in {"Сис", "Атмена"},
        )
        content = 'Процедура Тест()\n    Сообщить("СисАтмена");\nКонецПроцедуры\n'
        path = tmp_path / "TypoFirstFragment.bsl"
        path.write_text(content, encoding="utf-8")

        diags = [
            d
            for d in DiagnosticEngine(select={"BSL256"}).check_file(str(path))
            if d.code == "BSL256"
        ]
        assert {d.message for d in diags} == {_rule_msg("BSL256")}

    def test_bslls_typo_skips_multiline_string_tokens(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "onec_hbk_bsl.analysis.bslls_typo.default_spell_fn",
            lambda word: word == "Физлицам",
        )
        content = (
            "Процедура Тест()\n"
            '    Текст = "Ошибка Физлицам\n'
            '        |продолжение";\n'
            "КонецПроцедуры\n"
        )
        path = tmp_path / "TypoMultilineString.bsl"
        path.write_text(content, encoding="utf-8")

        diags = [
            d
            for d in DiagnosticEngine(select={"BSL256"}).check_file(str(path))
            if d.code == "BSL256"
        ]
        assert not diags

    def test_bslls_typo_skips_known_domain_abbreviations(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "onec_hbk_bsl.analysis.bslls_typo.default_spell_fn",
            lambda word: word == "Инфо",
        )
        content = "Процедура Тест()\n    ИнфоНадпись = 1;\nКонецПроцедуры\n"
        path = tmp_path / "TypoInfoAbbreviation.bsl"
        path.write_text(content, encoding="utf-8")

        diags = [
            d
            for d in DiagnosticEngine(select={"BSL256"}).check_file(str(path))
            if d.code == "BSL256"
        ]
        assert not diags

    def test_bslls_typo_skips_known_corpus_false_positive_fragments(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "onec_hbk_bsl.analysis.bslls_typo.default_spell_fn",
            lambda word: word in {"Прил", "Валидна", "Атмена"},
        )
        content = 'Процедура Тест()\n    Сообщить("ПрилВалиднаАтмена");\nКонецПроцедуры\n'
        path = tmp_path / "TypoKnownCorpusNoise.bsl"
        path.write_text(content, encoding="utf-8")

        diags = [
            d
            for d in DiagnosticEngine(select={"BSL256"}).check_file(str(path))
            if d.code == "BSL256"
        ]
        assert len(diags) == 1
        assert diags[0].message == _rule_msg("BSL256")

    def test_bslls_typo_skips_marketplace_terms(self, tmp_path: Path) -> None:
        content = 'Процедура Тест()\n    Сообщить("Маркетплейсы и маркетплейсы");\nКонецПроцедуры\n'
        path = tmp_path / "TypoMarketplace.bsl"
        path.write_text(content, encoding="utf-8")

        diags = [
            d
            for d in DiagnosticEngine(select={"BSL256"}).check_file(str(path))
            if d.code == "BSL256"
        ]
        assert not diags

    def test_bslls_typo_tax_monitor_token_parity(self, tmp_path: Path) -> None:
        content = (
            "Процедура Тест()\n"
            '    Сообщить("Нулевка Буд Кор Салатовый");\n'
            '    Сообщить("Физлица Юрлица Декапитализировать Субконто");\n'
            "КонецПроцедуры\n"
        )
        path = tmp_path / "TypoTaxTokens.bsl"
        path.write_text(content, encoding="utf-8")

        diags = [
            d
            for d in DiagnosticEngine(select={"BSL256"}).check_file(str(path))
            if d.code == "BSL256"
        ]
        messages = {d.message for d in diags}
        assert messages == {_rule_msg("BSL256")}

    def test_bslls_typo_skips_generic_domain_terms(self, tmp_path: Path) -> None:
        content = (
            "Процедура Тест()\n"
            '    Сообщить("ТестЭДО Тов Нал Прокси Токен Маппинг Парсинг Прослеживаемости");\n'
            "КонецПроцедуры\n"
        )
        path = tmp_path / "TypoGenericDomainTerms.bsl"
        path.write_text(content, encoding="utf-8")

        diags = [
            d
            for d in DiagnosticEngine(select={"BSL256"}).check_file(str(path))
            if d.code == "BSL256"
        ]
        assert not diags

    def test_bslls_typo_reports_reference_short_fragments(self, tmp_path: Path) -> None:
        content = (
            'Функция ТипПрото_Информация()\n    Сообщить("Кор Рег Деб Сис Дис");\nКонецФункции\n'
        )
        path = tmp_path / "TypoReferenceShortFragments.bsl"
        path.write_text(content, encoding="utf-8")

        diags = [
            d
            for d in DiagnosticEngine(select={"BSL256"}).check_file(str(path))
            if d.code == "BSL256"
        ]
        messages = {d.message for d in diags}
        assert messages == {_rule_msg("BSL256")}

    def test_bslls_typo_anchor_not_shifted_on_crlf_lines(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(
            "onec_hbk_bsl.analysis.bslls_typo.default_spell_fn",
            lambda word: word == "Атмена",
        )
        content = 'Процедура Тест()\r\n    Сообщить("Атмена");\r\nКонецПроцедуры\r\n'
        path = tmp_path / "TypoCrlfAnchor.bsl"
        path.write_text(content, encoding="utf-8", newline="")

        diags = [
            d
            for d in DiagnosticEngine(select={"BSL256"}).check_file(str(path))
            if d.code == "BSL256"
        ]
        assert len(diags) == 1
        assert diags[0].line == 2
        assert diags[0].character == content.splitlines()[1].index('"')
