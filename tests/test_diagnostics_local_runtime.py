"""Local runtime tail diagnostics."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from onec_hbk_bsl.analysis.diagnostic.domain import ModuleModel
from onec_hbk_bsl.analysis.diagnostics import (
    Diagnostic,
    DiagnosticEngine,
    Severity,
)
from onec_hbk_bsl.indexer.metadata_parser import MetaMember, MetaObject
from onec_hbk_bsl.indexer.symbol_index import SymbolIndex
from tests.diagnostic_test_support import _check, _codes, _rule_msg

pytestmark = pytest.mark.unit


# BSL237 — TestBsl237RedundantAccessToObjectParity
class TestBsl237RedundantAccessToObjectParity:
    def test_this_object_property_access_is_reported(self, tmp_path: Path) -> None:
        content = """\
            Процедура ПередЗаписью(Отказ, РежимЗаписи)
                Значение = ЭтотОбъект.ДополнительныеСвойства.Свойство("Флаг");
            КонецПроцедуры
        """
        path = tmp_path / "AccountingRegisters" / "Тест" / "Ext" / "RecordSetModule.bsl"
        path.parent.mkdir(parents=True)
        path.write_text(textwrap.dedent(content), encoding="utf-8")
        diags = DiagnosticEngine(select={"BSL237"}).check_file(str(path))
        bsl237 = [d for d in diags if d.code == "BSL237"]
        assert len(bsl237) == 1
        assert bsl237[0].line == 2
        assert bsl237[0].character == 15

    def test_plain_identifier_without_this_object_is_clean(self, tmp_path: Path) -> None:
        content = """\
            Процедура ПередЗаписью(Отказ, РежимЗаписи)
                Значение = ДополнительныеСвойства.Свойство("Флаг");
            КонецПроцедуры
        """
        path = tmp_path / "AccountingRegisters" / "Тест" / "Ext" / "RecordSetModule.bsl"
        path.parent.mkdir(parents=True)
        path.write_text(textwrap.dedent(content), encoding="utf-8")
        diags = DiagnosticEngine(select={"BSL237"}).check_file(str(path))
        assert "BSL237" not in _codes(diags)

    def test_direct_this_object_method_call_is_not_reported(self, tmp_path: Path) -> None:
        content = """\
            Процедура Сформировать()
                Макет = ЭтотОбъект.ПолучитьМакет("СхемаВыгрузки");
            КонецПроцедуры
        """
        path = tmp_path / "Reports" / "Тест" / "Ext" / "ObjectModule.bsl"
        path.parent.mkdir(parents=True)
        path.write_text(textwrap.dedent(content), encoding="utf-8")
        diags = DiagnosticEngine(select={"BSL237"}).check_file(str(path))
        assert "BSL237" not in _codes(diags)


# BSL265 — TestBsl265UselessTernaryOperatorParity
class TestBsl265UselessTernaryOperatorParity:
    def test_boolean_literal_branch_with_boolean_member_is_reported(self, tmp_path: Path) -> None:
        content = """\
            Процедура Проверить()
                УсловиеВыполнено = ?(НастройкиКС.Безусловно, Истина, ДанныеКС.ТипПлательщика1);
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL265"})
        bsl265 = [d for d in diags if d.code == "BSL265"]
        assert len(bsl265) == 1
        assert bsl265[0].line == 2

    def test_boolean_literal_branch_with_boolean_call_is_reported(self, tmp_path: Path) -> None:
        content = """\
            Процедура Проверить()
                Если ?(СтрНайти(Узел.Обязательность, "О") <> 0,
                    РегламентированнаяОтчетность.ИмеютсяАналогичныеСоседниеУзлыКлюч(Узел), Истина) Тогда
                КонецЕсли;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL265"})
        assert "BSL265" in _codes(diags)

    def test_boolean_literal_branch_with_non_boolean_value_is_clean(self, tmp_path: Path) -> None:
        content = """\
            Процедура Проверить()
                А = ?(Б = 1, True, 1);
                Б = ?(Б = 0, 0, False);
                БулевоЗначение = ?(ЗначениеЗаполнено(СсылкаНаСправочник), СсылкаНаСправочник.БулевоПоле, Ложь);
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL265"})
        assert "BSL265" not in _codes(diags)


# BSL175, BSL176, BSL177, BSL178, BSL179, BSL182, BSL195 — TestDeprecatedApiParityBatch
class TestDeprecatedApiParityBatch:
    def test_bsl175_deprecated_chart_attribute_and_global_method(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Значение = ОбластьПостроенияДиаграммы.ОтображатьШкалу;
                ОчиститьЖурналРегистрации(Отбор);
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL175"})
        bsl175 = [d for d in diags if d.code == "BSL175"]
        assert len(bsl175) == 2
        assert all(d.message == _rule_msg("BSL175") for d in bsl175)

    def test_bsl175_deprecated_chart_method_and_enum(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Диаграмма.ПолучитьПалитру();
                Значение = ГруппировкаПодчиненныхЭлементовФормы.Горизонтальная;
                Значение = ОриентацияМетокДиаграммы.Авто;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL175"})
        bsl175 = [d for d in diags if d.code == "BSL175"]
        assert len(bsl175) == 3

    def test_bsl175_ignores_strings_comments_and_current_names(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                // Диаграмма.ПолучитьПалитру();
                Текст = "ОчиститьЖурналРегистрации(Отбор)";
                Значение = ГруппировкаПодчиненныхЭлементовФормы.ГоризонтальнаяВсегда;
                Значение = ОриентацияПодписейДиаграммы.Авто;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL175"})
        assert "BSL175" not in _codes(diags)

    def test_bsl176_same_file_deprecated_method_call(self, tmp_path: Path) -> None:
        content = """\
            // Deprecated. Use НовыйМетод instead.
            Процедура СтарыйМетод()
            КонецПроцедуры

            Процедура НовыйМетод()
                СтарыйМетод();
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL176"})
        bsl176 = [d for d in diags if d.code == "BSL176"]
        assert len(bsl176) == 1
        assert bsl176[0].line == 6
        assert bsl176[0].message == _rule_msg("BSL176")

    def test_bsl176_same_file_ru_deprecated_method_call(self, tmp_path: Path) -> None:
        content = """\
            // Устарела. Используйте НовыйМетод.
            Процедура СтарыйМетод()
            КонецПроцедуры

            Процедура НовыйМетод()
                СтарыйМетод();
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL176"})
        bsl176 = [d for d in diags if d.code == "BSL176"]
        assert len(bsl176) == 1
        assert bsl176[0].line == 6

    def test_bsl176_doc_words_about_stale_data_do_not_deprecate_method(
        self, tmp_path: Path
    ) -> None:
        content = """\
            // Возвращаемое значение:
            //  - Обновленную сессию, если сессия устарела.
            Функция ПолучитьСессию()
            КонецФункции

            Процедура Тест()
                ПолучитьСессию();
            КонецПроцедуры
        """
        assert "BSL176" not in _codes(_check(content, tmp_path, select={"BSL176"}))

    def test_bsl176_doc_words_about_deprecated_parameter_do_not_deprecate_method(
        self, tmp_path: Path
    ) -> None:
        content = """\
            // Параметры:
            //  ДанныеДокумента - Структура - Устарело, не используется.
            Функция Контракт_Документ()
            КонецФункции

            Процедура Тест()
                Контракт_Документ();
            КонецПроцедуры
        """
        assert "BSL176" not in _codes(_check(content, tmp_path, select={"BSL176"}))

    def test_bsl176_doc_shouty_obsolete_word_is_not_bslls_deprecated_block(
        self, tmp_path: Path
    ) -> None:
        content = """\
            // УСТАРЕЛ! Вместо данного метода следует использовать НовыйМетод()
            Функция ПриложениеСтаршеВерсии()
            КонецФункции

            Процедура Тест()
                ПриложениеСтаршеВерсии();
            КонецПроцедуры
        """
        assert "BSL176" not in _codes(_check(content, tmp_path, select={"BSL176"}))

    def test_bsl176_metadata_deleted_prefix_property(self, tmp_path: Path) -> None:
        path = tmp_path / "Module.bsl"
        path.write_text(
            textwrap.dedent(
                """\
                Процедура Тест()
                    Значение = Метаданные.Справочники.Контрагенты.УдалитьСтарыйРеквизит;
                КонецПроцедуры
                """
            ),
            encoding="utf-8",
        )
        idx = SymbolIndex(db_path=":memory:")
        try:
            idx.upsert_metadata(
                [
                    MetaObject(
                        name="Контрагенты",
                        kind="Catalog",
                        members=[
                            MetaMember(
                                name="УдалитьСтарыйРеквизит",
                                kind="attribute",
                                parent_name="Контрагенты",
                                parent_kind="Catalog",
                            )
                        ],
                    )
                ]
            )
            diags = DiagnosticEngine(select={"BSL176"}, symbol_index=idx).check_file(str(path))
        finally:
            idx.close()

        bsl176 = [d for d in diags if d.code == "BSL176"]
        assert len(bsl176) == 1
        assert (bsl176[0].line, bsl176[0].character, bsl176[0].end_character) == (2, 50, 71)
        assert bsl176[0].message == _rule_msg("BSL176")

    def test_bsl176_deleted_prefix_method_call_is_not_metadata_property(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "Module.bsl"
        path.write_text(
            textwrap.dedent(
                """\
                Процедура Тест()
                    Метаданные.Справочники.Контрагенты.УдалитьСтарыйРеквизит();
                КонецПроцедуры
                """
            ),
            encoding="utf-8",
        )
        idx = SymbolIndex(db_path=":memory:")
        try:
            idx.upsert_metadata(
                [
                    MetaObject(
                        name="Контрагенты",
                        kind="Catalog",
                        members=[
                            MetaMember(
                                name="УдалитьСтарыйРеквизит",
                                kind="attribute",
                                parent_name="Контрагенты",
                                parent_kind="Catalog",
                            )
                        ],
                    )
                ]
            )
            diags = DiagnosticEngine(select={"BSL176"}, symbol_index=idx).check_file(str(path))
        finally:
            idx.close()

        assert "BSL176" not in _codes(diags)

    def test_bsl176_deprecated_platform_global_method(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Текст = ПодробноеПредставлениеОшибки(ИнформацияОбОшибке());
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL176"}) if d.code == "BSL176"]
        assert len(diags) == 1
        assert (diags[0].line, diags[0].character, diags[0].end_character) == (2, 12, 40)

    def test_bsl176_deprecated_platform_qualified_method(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Текст = ОбработкаОшибок.ПодробноеПредставлениеОшибки(ИнформацияОбОшибке());
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL176"})
        bsl176 = [d for d in diags if d.code == "BSL176"]
        assert len(bsl176) == 1
        assert (bsl176[0].line, bsl176[0].character, bsl176[0].end_character) == (2, 28, 56)

    def test_bsl177_deprecated_client_app_method(self, tmp_path: Path) -> None:
        content = """\
            Процедура Test()
                test = GetShortApplicationCaption();
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL177"})
        bsl177 = [d for d in diags if d.code == "BSL177"]
        assert len(bsl177) == 1
        assert bsl177[0].message == _rule_msg("BSL177")

    def test_bsl177_reports_all_deprecated_8310_client_app_methods(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                УстановитьКраткийЗаголовокПриложения("x");
                ПолучитьКраткийЗаголовокПриложения();
                УстановитьЗаголовокКлиентскогоПриложения("x");
                ПолучитьЗаголовокКлиентскогоПриложения();
                ТекущийВариантОсновногоШрифтаКлиентскогоПриложения();
                ТекущийВариантИнтерфейсаКлиентскогоПриложения();
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL177"}) if d.code == "BSL177"]
        assert [(d.line, d.character) for d in diags] == [
            (2, 4),
            (3, 4),
            (4, 4),
            (5, 4),
            (6, 4),
            (7, 4),
        ]
        assert diags[0].end_character == 40
        assert diags[2].end_character == 44

    def test_bsl177_ignores_qualified_calls_strings_comments_and_prefixes(
        self, tmp_path: Path
    ) -> None:
        content = """\
            Процедура Тест()
                Объект.ПолучитьКраткийЗаголовокПриложения();
                Текст = "ПолучитьКраткийЗаголовокПриложения()";
                // ПолучитьКраткийЗаголовокПриложения();
                ПолучитьКраткийЗаголовокПриложенияНовый();
            КонецПроцедуры
        """
        assert "BSL177" not in _codes(_check(content, tmp_path, select={"BSL177"}))

    def test_bsl178_skips_before_platform_8317_compatibility(self, tmp_path: Path) -> None:
        (tmp_path / "Configuration.xml").write_text(
            "<Configuration><CompatibilityMode>Version8_3_14</CompatibilityMode></Configuration>",
            encoding="utf-8",
        )
        path = tmp_path / "ObjectModule.bsl"
        path.write_text(
            textwrap.dedent(
                """\
                Процедура Тест()
                    Текст = ПодробноеПредставлениеОшибки(ИнформацияОбОшибке());
                КонецПроцедуры
                """
            ),
            encoding="utf-8",
        )
        diags = DiagnosticEngine(select={"BSL178"}).check_file(str(path))
        assert "BSL178" not in _codes(diags)

    def test_bsl178_reports_on_platform_8317_compatibility(self, tmp_path: Path) -> None:
        (tmp_path / "Configuration.xml").write_text(
            "<Configuration><CompatibilityMode>Version8_3_17</CompatibilityMode></Configuration>",
            encoding="utf-8",
        )
        path = tmp_path / "ObjectModule.bsl"
        path.write_text(
            textwrap.dedent(
                """\
                Процедура Тест()
                    Текст = ПодробноеПредставлениеОшибки(ИнформацияОбОшибке());
                КонецПроцедуры
                """
            ),
            encoding="utf-8",
        )
        diags = DiagnosticEngine(select={"BSL178"}).check_file(str(path))
        assert "BSL178" in _codes(diags)

    def test_bsl178_reports_all_deprecated_8317_global_methods(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                А = КраткоеПредставлениеОшибки(ИнформацияОбОшибке());
                Б = ПодробноеПредставлениеОшибки(ИнформацияОбОшибке());
                ПоказатьИнформациюОбОшибке(ИнформацияОбОшибке());
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL178"}) if d.code == "BSL178"]
        assert [(d.line, d.character, d.end_character) for d in diags] == [
            (2, 8, 34),
            (3, 8, 36),
            (4, 4, 30),
        ]

    def test_bsl178_ignores_object_calls_strings_and_comments(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                А = ОбработкаОшибок.КраткоеПредставлениеОшибки(ИнформацияОбОшибке());
                Текст = "ПодробноеПредставлениеОшибки()";
                // ПоказатьИнформациюОбОшибке(ИнформацияОбОшибке());
            КонецПроцедуры
        """
        assert "BSL178" not in _codes(_check(content, tmp_path, select={"BSL178"}))

    def test_bsl179_managed_form_type(self, tmp_path: Path) -> None:
        content = """\
            Процедура Test()
                Если Type(Form) = Type("ManagedForm") Тогда
                    Возврат;
                КонецЕсли;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL179"})
        bsl179 = [d for d in diags if d.code == "BSL179"]
        assert len(bsl179) == 1
        assert bsl179[0].line == 2
        assert (bsl179[0].character, bsl179[0].end_character) == (27, 40)

    def test_bsl179_ignores_strings_comments_and_non_type_calls(self, tmp_path: Path) -> None:
        content = """\
            Процедура Test()
                Text = "Тип(""УправляемаяФорма"")";
                // Если Тип(Форма) = Тип("УправляемаяФорма") Тогда
                ТипФормы("УправляемаяФорма");
            КонецПроцедуры
        """
        assert "BSL179" not in _codes(_check(content, tmp_path, select={"BSL179"}))

    def test_bsl182_excessive_autotest_check_official_patterns(self, tmp_path: Path) -> None:
        content = """\
            Процедура ПриСозданииНаСервере()
                Если Параметры.Свойство("АвтоТест") Тогда
                    Возврат;
                КонецЕсли;
            КонецПроцедуры

            Процедура ОбработкаЗаполнения(ДанныеЗаполнения)
                Если ДанныеЗаполнения = "АвтоТест" Тогда
                    Возврат;
                КонецЕсли;
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL182"}) if d.code == "BSL182"]
        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (2, 4, 4, 14),
            (8, 4, 10, 14),
        ]
        assert {d.severity for d in diags} == {Severity.INFORMATION}

    def test_bsl182_requires_only_return_in_if_body(self, tmp_path: Path) -> None:
        content = """\
            Процедура БезОшибок()
                Если Перечень.Свойство("АвтоТест") Тогда
                    Перечень.Удалить("АвтоТест");
                    Возврат;
                КонецЕсли;
            КонецПроцедуры
        """
        assert "BSL182" not in _codes(_check(content, tmp_path, select={"BSL182"}))

    def test_bsl195_get_form_method(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Форма = ПолучитьФорму("Обработка.УниверсальныйРедактор.Форма");
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL195"})
        bsl195 = [d for d in diags if d.code == "BSL195"]
        assert len(bsl195) == 1
        assert bsl195[0].line == 2
        assert bsl195[0].message == _rule_msg("BSL195")

    def test_bsl195_reports_receiver_get_form_and_ignores_strings_comments(
        self, tmp_path: Path
    ) -> None:
        content = """\
            Процедура Тест()
                Форма = Док.ПолучитьФорму("ФормаДокумента");
                Текст = "ПолучитьФорму()";
                // Форма = ПолучитьФорму("Форма");
            КонецПроцедуры
        """
        bsl195 = [d for d in _check(content, tmp_path, select={"BSL195"}) if d.code == "BSL195"]
        assert [(d.line, d.character, d.end_character) for d in bsl195] == [(2, 16, 29)]


# BSL229, BSL275, BSL278 — TestLocalXmlParityBatch
class TestLocalXmlParityBatch:
    def test_bsl229_reports_ordinary_application_flags_from_configuration(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path / "Config"
        (root / "Ext").mkdir(parents=True)
        (root / "Configuration.xml").write_text(
            textwrap.dedent(
                """\
                <Configuration>
                    <UseManagedFormInOrdinaryApplication>false</UseManagedFormInOrdinaryApplication>
                    <UseOrdinaryFormInManagedApplication>true</UseOrdinaryFormInManagedApplication>
                </Configuration>
                """
            ),
            encoding="utf-8",
        )
        module_path = root / "Ext" / "SessionModule.bsl"
        module_path.write_text(
            textwrap.dedent(
                """\
                Процедура ПриНачалеРаботыСистемы()
                КонецПроцедуры
                """
            ),
            encoding="utf-8",
        )
        diags = DiagnosticEngine(select={"BSL229"}).check_file(str(module_path))
        assert _codes(diags) == ["BSL229", "BSL229"]

    def test_bsl229_clean_recommended_ordinary_application_flags(self, tmp_path: Path) -> None:
        root = tmp_path / "Config"
        (root / "Ext").mkdir(parents=True)
        (root / "Configuration.xml").write_text(
            textwrap.dedent(
                """\
                <Configuration>
                    <UseManagedFormInOrdinaryApplication>true</UseManagedFormInOrdinaryApplication>
                    <UseOrdinaryFormInManagedApplication>false</UseOrdinaryFormInManagedApplication>
                </Configuration>
                """
            ),
            encoding="utf-8",
        )
        module_path = root / "Ext" / "SessionModule.bsl"
        module_path.write_text(
            "Процедура ПриНачалеРаботыСистемы()\nКонецПроцедуры\n",
            encoding="utf-8",
        )

        diags = DiagnosticEngine(select={"BSL229"}).check_file(str(module_path))
        assert "BSL229" not in _codes(diags)

    def test_bsl275_reports_missing_and_wrong_http_handlers(self, tmp_path: Path) -> None:
        root = tmp_path / "Config"
        module_path = root / "HTTPServices" / "Сервис" / "Ext" / "Module.bsl"
        module_path.parent.mkdir(parents=True)
        (root / "HTTPServices" / "Сервис.xml").write_text(
            textwrap.dedent(
                """\
                <HTTPService>
                    <UrlTemplates>
                        <Item>
                            <Methods>
                                <Item><Handler></Handler></Item>
                                <Item><Handler>Обработчик</Handler></Item>
                            </Methods>
                        </Item>
                    </UrlTemplates>
                </HTTPService>
                """
            ),
            encoding="utf-8",
        )
        module_path.write_text(
            textwrap.dedent(
                """\
                Процедура Обработчик(Запрос, Ответ)
                КонецПроцедуры
                """
            ),
            encoding="utf-8",
        )
        diags = DiagnosticEngine(select={"BSL275"}).check_file(str(module_path))
        assert _codes(diags) == ["BSL275", "BSL275"]
        assert any(diag.line == 1 for diag in diags)
        assert any(diag.line == 1 and diag.message == _rule_msg("BSL275") for diag in diags)

    def test_bsl278_reports_missing_web_service_handler(self, tmp_path: Path) -> None:
        root = tmp_path / "Config"
        module_path = root / "WebServices" / "Сервис" / "Ext" / "Module.bsl"
        module_path.parent.mkdir(parents=True)
        (root / "WebServices" / "Сервис.xml").write_text(
            textwrap.dedent(
                """\
                <WebService>
                    <Operations>
                        <Item><ProcedureName>НеСуществует</ProcedureName></Item>
                    </Operations>
                </WebService>
                """
            ),
            encoding="utf-8",
        )
        module_path.write_text(
            textwrap.dedent(
                """\
                Процедура Обработчик()
                КонецПроцедуры
                """
            ),
            encoding="utf-8",
        )
        diags = DiagnosticEngine(select={"BSL278"}).check_file(str(module_path))
        assert _codes(diags) == ["BSL278"]
        assert diags[0].message == _rule_msg("BSL278")


# BSL248 — TestBsl248SeveralCompilerDirectives
class TestBsl248SeveralCompilerDirectives:
    def test_two_directives_on_method_are_reported(self, tmp_path: Path) -> None:
        content = """\
            &НаКлиенте
            &НаСервере
            Процедура Тест()
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL248"})

        bsl248 = [diag for diag in diags if diag.code == "BSL248"]
        assert [
            (
                diag.line,
                diag.character,
                diag.end_line,
                diag.end_character,
                diag.severity,
                diag.message,
            )
            for diag in bsl248
        ] == [(3, 10, 3, 14, Severity.ERROR, _rule_msg("BSL248"))]

    def test_two_directives_on_module_variable_are_reported(self, tmp_path: Path) -> None:
        content = """\
            &НаКлиенте
            &НаСервере
            Перем Значение;
        """
        diags = _check(content, tmp_path, select={"BSL248"})

        assert _codes(diags).count("BSL248") == 1

    def test_single_and_separate_directives_are_clean(self, tmp_path: Path) -> None:
        content = """\
            &НаКлиенте
            Процедура Клиент()
            КонецПроцедуры

            &НаСервере
            Процедура Сервер()
            КонецПроцедуры

            // &НаКлиенте
            Текст = "&НаСервере";
        """
        diags = _check(content, tmp_path, select={"BSL248"})

        assert "BSL248" not in _codes(diags)


# BSL252 — TestBsl252ThisObjectAssign
class TestBsl252ThisObjectAssign:
    def test_this_object_assignment_in_form_module_reports(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                ЭтотОбъект = Новый Структура;
            КонецПроцедуры
        """
        path = tmp_path / "Forms" / "Форма" / "Ext" / "Form" / "Module.bsl"
        path.parent.mkdir(parents=True)
        path.write_text(textwrap.dedent(content), encoding="utf-8")

        diags = DiagnosticEngine(select={"BSL252"}).check_file(str(path))

        assert [(d.line, d.character, d.end_character) for d in diags if d.code == "BSL252"] == [
            (2, 4, 14),
        ]

    def test_this_object_property_assignment_is_clean(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                ЭтотОбъект.Реквизит = Значение;
            КонецПроцедуры
        """
        path = tmp_path / "Forms" / "Форма" / "Ext" / "Form" / "Module.bsl"
        path.parent.mkdir(parents=True)
        path.write_text(textwrap.dedent(content), encoding="utf-8")

        assert "BSL252" not in _codes(DiagnosticEngine(select={"BSL252"}).check_file(str(path)))


# BSL259 — TestBsl259UnknownPreprocessorSymbol
class TestBsl259UnknownPreprocessorSymbol:
    def test_unknown_preprocessor_symbol_reports(self, tmp_path: Path) -> None:
        content = """\
            #Если НеизвестныйСимвол Тогда
            Сообщить("x");
            #КонецЕсли
        """
        diags = _check(content, tmp_path, select={"BSL259"})

        assert [(d.line, d.character, d.end_character) for d in diags if d.code == "BSL259"] == [
            (1, 6, 23),
        ]

    def test_known_preprocessor_symbol_is_clean(self, tmp_path: Path) -> None:
        content = """\
            #Если Клиент Тогда
            Сообщить("x");
            #КонецЕсли
        """

        assert "BSL259" not in _codes(_check(content, tmp_path, select={"BSL259"}))


# BSL217 — TestBsl217MissingTempStorageDeletion
class TestBsl217MissingTempStorageDeletion:
    def test_missing_delete_detected(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест(Адрес)
                Данные = ПолучитьИзВременногоХранилища(Адрес);
                Использовать(Данные);
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL217"})
        assert [(d.line, d.character, d.end_character) for d in diags if d.code == "BSL217"] == [
            (2, 13, 49),
        ]

    def test_delete_same_address_suppresses_diagnostic(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест(Адрес)
                Данные = ПолучитьИзВременногоХранилища(Адрес);
                Использовать(Данные);
                УдалитьИзВременногоХранилища(Адрес);
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL217"})
        assert "BSL217" not in _codes(diags)

    def test_delete_other_address_does_not_suppress_diagnostic(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест(Адрес, ДругойАдрес)
                Данные = ПолучитьИзВременногоХранилища(Адрес);
                УдалитьИзВременногоХранилища(ДругойАдрес);
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL217"})
        assert "BSL217" in _codes(diags)

    def test_enabled_by_default(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест(Адрес)
                Данные = ПолучитьИзВременногоХранилища(Адрес);
            КонецПроцедуры
        """
        diags = _check(content, tmp_path)
        assert "BSL217" in _codes(diags)

    def test_put_to_temp_storage_is_not_bsl217(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест(Данные, УникальныйИдентификатор)
                Адрес = ПоместитьВоВременноеХранилище(Данные, УникальныйИдентификатор);
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL217"})
        assert "BSL217" not in _codes(diags)

    @pytest.mark.external_bslls
    def test_matches_bslls_fixture(self) -> None:
        fixture = Path(
            ".tmp/external-fixtures/bsl-language-server/src/test/resources/diagnostics/"
            "MissingTempStorageDeletionDiagnostic.bsl"
        )
        if not fixture.exists():
            pytest.skip("BSLLS fixture is not available")
        diags = [
            diag
            for diag in DiagnosticEngine(select={"BSL217"}).check_file(str(fixture))
            if diag.code == "BSL217"
        ]
        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (4, 24, 4, 77),
            (14, 24, 14, 77),
            (22, 24, 22, 77),
            (34, 24, 34, 77),
        ]


# BSL003 — TestBsl003NonExportInApiRegion
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
        assert bsl003[0].character == 10
        assert bsl003[0].message == _rule_msg("BSL003")

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


# BSL009 — TestBsl009SelfAssign
class TestBsl009SelfAssign:
    def test_self_assign_detected(self, tmp_path: Path) -> None:
        content = "Процедура Тест()\n    Переменная = Переменная;\nКонецПроцедуры\n"
        diags = _check(content, tmp_path)
        bsl009 = [d for d in diags if d.code == "BSL009"]
        assert len(bsl009) >= 1
        assert bsl009[0].message == _rule_msg("BSL009")

    def test_normal_assign_no_warning(self, tmp_path: Path) -> None:
        content = "Процедура Тест()\n    А = Б;\nКонецПроцедуры\n"
        diags = _check(content, tmp_path)
        assert "BSL009" not in _codes(diags)

    def test_property_assign_same_identifier_not_self_assign(self, tmp_path: Path) -> None:
        # BSLLS does not flag Obj.Field = Field as SelfAssign.
        content = "Процедура Тест()\n    ОписаниеСертификата.ИНН = ИНН;\nКонецПроцедуры\n"
        diags = _check(content, tmp_path)
        assert "BSL009" not in _codes(diags)

    def test_self_assign_in_comment_ignored(self, tmp_path: Path) -> None:
        content = "// Х = Х;\n"
        diags = _check(content, tmp_path)
        assert "BSL009" not in _codes(diags)


# BSL007, BSL009, BSL012, BSL014, BSL029 — TestRuleSelection
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
        content = 'Пароль = "секрет123";\n'
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
            "// BSLLS:UsingHardcodeSecretInformation-off\n"  # line 1 → BSL012 off
            'Пароль = "СуперСекрет2024!";\n'  # line 2 → suppressed
            "// BSLLS:UsingHardcodeSecretInformation-on\n"  # line 3 → re-enable
            'Пароль = "МойПароль123@#";\n'  # line 4 → reported
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
        content = '// BSLLS-off\nПароль = "секрет123";\n// BSLLS-on\n'
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
            'Пароль = "секрет123";  // noqa: BSL009\n'  # both suppressions active
            "// BSLLS:UsingHardcodeSecretInformation-on\n"
        )
        diags = _check(content, tmp_path)
        assert "BSL012" not in _codes(diags)

    def test_bslls_unknown_name_ignored(self, tmp_path: Path) -> None:
        """Unknown BSLLS names are silently ignored — other rules still fire."""
        content = '// BSLLS:NonExistentRule-off\nПароль = "секрет123";\n'
        diags = _check(content, tmp_path)
        assert "BSL012" in _codes(diags)

    def test_bslls_nested_independent_rules(self, tmp_path: Path) -> None:
        """Two rules can be independently nested."""
        content = (
            "// BSLLS:UsingHardcodeSecretInformation-off\n"  # BSL012 off
            "// BSLLS:LineLength-off\n"  # BSL014 off
            'Пароль = "секрет123";\n'  # both suppressed
            "// BSLLS:UsingHardcodeSecretInformation-on\n"  # BSL012 back on
            'Пароль = "abc";\n'  # BSL012 fires, BSL014 still off
            "// BSLLS:LineLength-on\n"
        )
        diags = _check(content, tmp_path)
        # Line 3: both should be suppressed
        assert all(d.code not in {"BSL012", "BSL014"} for d in diags if d.line == 3)
        # Line 5: BSL012 should fire again (if token is a secret-looking string)
        # BSL014 still off → no line-length errors on line 5

    def test_bslls_overlapping_specific_blocks_union_codes(self, tmp_path: Path) -> None:
        """Overlapping BSLLS blocks for different rules suppress both rules."""
        content = (
            "// BSLLS:Typo-off\n"
            "// BSLLS:MagicNumber-off\n"
            "Возврат 255;\n"
            "// BSLLS:MagicNumber-on\n"
            "// BSLLS:Typo-on\n"
        )
        diags = _check(content, tmp_path, select={"BSL029"})
        assert "BSL029" not in _codes(diags)

    def test_bslls_comment_line_is_seen_when_string_state_is_unbalanced(
        self, tmp_path: Path
    ) -> None:
        """Whole-line BSLLS comments remain comments even after broken string state."""
        content = (
            'Текст = "broken\n// BSLLS:MagicNumber-off\nВозврат 255;\n// BSLLS:MagicNumber-on\n'
        )
        diags = _check(content, tmp_path, select={"BSL029"})
        assert "BSL029" not in _codes(diags)


# registry/meta — TestRuleMetadata
class TestRuleMetadata:
    def test_all_rules_have_metadata(self) -> None:
        from onec_hbk_bsl.analysis.diagnostics import _BSLLS_NAME_TO_CODE, RULE_METADATA

        assert set(RULE_METADATA) == set(_BSLLS_NAME_TO_CODE.values())

    def test_metadata_has_required_fields(self) -> None:
        from onec_hbk_bsl.analysis.diagnostics import RULE_METADATA

        required = {"name", "description", "severity"}
        for code, meta in RULE_METADATA.items():
            missing = required - set(meta.keys())
            assert not missing, f"{code} is missing fields: {missing}"

    def test_all_bsl041_rules_have_metadata(self) -> None:
        from onec_hbk_bsl.analysis.diagnostics import _BSLLS_NAME_TO_CODE, RULE_METADATA

        assert len(RULE_METADATA) == len(set(_BSLLS_NAME_TO_CODE.values()))


# BSL020 — TestBsl020ExcessiveNesting
class TestBsl020ExcessiveNesting:
    def test_clean_cst_does_not_fall_back_to_regex(self, tmp_path: Path, monkeypatch) -> None:
        content = """\
            Процедура Тест(А)
                Если А Тогда
                    А = 1;
                КонецЕсли;
            КонецПроцедуры
        """

        def fail_fallback(*args, **kwargs):
            raise AssertionError("BSL020 regex fallback must not run after clean CST")

        monkeypatch.setattr(ModuleModel, "validate_excessive_nesting", fail_fallback)

        diags = _check(content, tmp_path, max_nesting_depth=4, select={"BSL020"})
        assert "BSL020" not in _codes(diags)

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

    def test_try_block_counted_in_nesting(self, tmp_path: Path) -> None:
        """BSLLS parity: Try/Попытка contributes to nested statements depth."""
        content = """\
            Процедура Тест(А, Б, В)
                Если А Тогда
                    Если Б Тогда
                        Попытка
                            Если В Тогда
                                А = 1;
                            КонецЕсли;
                        КонецПопытки;
                    КонецЕсли;
                КонецЕсли;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, max_nesting_depth=3)
        assert "BSL020" in _codes(diags)

    def test_single_deep_chain_reported_once(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест(А, Б, В)
                Если А Тогда
                    Если Б Тогда
                        Если В Тогда
                            Если А И Б Тогда
                                Если А Тогда
                                    А = 1;
                                КонецЕсли;
                            КонецЕсли;
                        КонецЕсли;
                    КонецЕсли;
                КонецЕсли;
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, max_nesting_depth=4) if d.code == "BSL020"]
        assert len(diags) == 1

    def test_regex_fallback_reports_each_overlimit_leaf_sibling(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест(А)
                Если А Тогда
                    Если А Тогда
                        Если А Тогда
                            Если А Тогда
                                Если А Тогда
                                КонецЕсли;
                                Если А Тогда
                                КонецЕсли;
                            КонецЕсли;
                        КонецЕсли;
                    КонецЕсли;
                КонецЕсли;
            КонецПроцедуры
        """
        path = tmp_path / "t.bsl"
        path.write_text(content, encoding="utf-8")
        lines = content.splitlines()
        diags = ModuleModel(str(path)).validate_excessive_nesting(
            lines,
            procs=[],
            max_nesting_depth=4,
        )
        assert [d.line for d in diags] == [6, 8]


# BSL027 — TestBsl027UseGoto
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

    def test_method_named_goto_is_not_operator(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                ПотокЗаписи.Перейти(Позиция);
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL027"})
        assert "BSL027" not in _codes(diags)

    @pytest.mark.external_bslls
    def test_matches_bslls_fixture(self) -> None:
        fixture = Path(
            ".tmp/external-fixtures/bsl-language-server/src/test/resources/diagnostics/UsingGotoDiagnostic.bsl"
        )
        if not fixture.exists():
            pytest.skip("BSLLS fixture is not available")
        diags = [
            diag
            for diag in DiagnosticEngine(select={"BSL027"}).check_file(str(fixture))
            if diag.code == "BSL027"
        ]
        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (9, 4, 9, 14),
            (23, 8, 23, 22),
        ]


# BSL028 — TestBsl028MissingCodeTryCatchEx
class TestBsl028MissingCodeTryCatchEx:
    def test_empty_except_detected(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Попытка
                    Действие();
                Исключение

                КонецПопытки;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL028"})
        bsl028 = [d for d in diags if d.code == "BSL028"]
        assert [(d.line, d.character, d.end_character, d.severity) for d in bsl028] == [
            (4, 4, 14, Severity.ERROR),
        ]

    def test_comment_only_except_detected_by_default(self, tmp_path: Path) -> None:
        content = """\
            Функция Тест()
                Попытка
                    Действие();
                Исключение
                    // Только комментарий
                КонецПопытки;
                Возврат 1;
            КонецФункции
        """
        diags = _check(content, tmp_path, select={"BSL028"})
        assert [(d.line, d.character, d.end_character) for d in diags if d.code == "BSL028"] == [
            (4, 4, 14),
        ]

    def test_non_empty_except_not_reported(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Попытка
                    Действие();
                Исключение
                    ОбработатьОшибку(ОписаниеОшибки());
                КонецПопытки;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL028"})
        assert "BSL028" not in _codes(diags)

    def test_risky_call_outside_try_is_not_bsl028(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Выполнить("Сообщить(1)");
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL028"})
        assert "BSL028" not in _codes(diags)

    @pytest.mark.external_bslls
    def test_matches_bslls_fixture(self) -> None:
        fixture = Path(
            ".tmp/external-fixtures/bsl-language-server/src/test/resources/diagnostics/"
            "MissingCodeTryCatchExDiagnostic.bsl"
        )
        if not fixture.exists():
            pytest.skip("BSLLS fixture is not available")
        diags = [
            diag
            for diag in DiagnosticEngine(select={"BSL028"}).check_file(str(fixture))
            if diag.code == "BSL028"
        ]
        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (24, 4, 24, 14),
            (33, 4, 33, 14),
            (51, 8, 51, 18),
        ]


# BSL032 — TestBsl032FunctionReturnValue
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


# BSL033 — TestBsl033QueryInLoop
class TestBsl033QueryInLoop:
    def test_query_in_foreach_detected(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест(Коллекция)
                Запрос = Новый Запрос;
                Для Каждого Элемент Из Коллекция Цикл
                    Результат = Запрос.Выполнить();
                КонецЦикла;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path)
        bsl033 = [diag for diag in diags if diag.code == "BSL033"]
        assert [(diag.line, diag.character, diag.end_character) for diag in bsl033] == [
            (4, 20, 38),
        ]

    def test_query_execute_chain_range_matches_full_call_chain(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест(Коллекция)
                Запрос = Новый Запрос;
                Для Каждого Элемент Из Коллекция Цикл
                    Результат = Запрос.Выполнить().Выгрузить();
                КонецЦикла;
            КонецПроцедуры
        """
        diags = [
            diag for diag in _check(content, tmp_path, select={"BSL033"}) if diag.code == "BSL033"
        ]
        assert [(diag.line, diag.character, diag.end_character) for diag in diags] == [
            (4, 20, 50),
        ]

    def test_query_in_while_detected(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Запрос = Новый Query;
                Пока Условие Цикл
                    Рез = Запрос.Execute();
                КонецЦикла;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path)
        assert "BSL033" in _codes(diags)

    def test_unknown_execute_in_loop_not_reported(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Пока Условие Цикл
                    Рез = Запрос.Выполнить();
                    Ответ = ЗапросHTTP.Execute();
                КонецЦикла;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL033"})
        assert "BSL033" not in _codes(diags)

    def test_query_type_is_inherited_from_assignment(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Запрос = Новый Запрос;
                ДругойЗапрос = Запрос;
                Пока Условие Цикл
                    Рез = ДругойЗапрос.Выполнить();
                КонецЦикла;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL033"})
        assert "BSL033" in _codes(diags)

    def test_query_outside_loop_no_warning(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Запрос = Новый Запрос;
                Результат = Запрос.Выполнить();
            КонецПроцедуры
        """
        diags = _check(content, tmp_path)
        assert "BSL033" not in _codes(diags)


# BSL039 — TestBsl039NestedTernary
class TestBsl039NestedTernary:
    def test_nested_ternary_detected(self, tmp_path: Path) -> None:
        content = "А = ?(Б, ?(В, 1, 2), 3);\n"
        diags = _check(content, tmp_path)
        assert "BSL039" in _codes(diags)

    def test_simple_ternary_no_warning(self, tmp_path: Path) -> None:
        content = "А = ?(Б, 1, 2);\n"
        diags = _check(content, tmp_path)
        assert "BSL039" not in _codes(diags)

    def test_bslls_fixture_multiline_and_if_condition_ranges(self, tmp_path: Path) -> None:
        content = """\
ПериодПо = ?(Шапка.ЭтоУвольнение
           , Шапка.Дата
           , ?(Шапка.ЭтоАванс
             , Дата( Год(Шапка.ПериодРегистрации)
                   , Месяц(Шапка.ПериодРегистрации)
                   , 15
                   )
             , КонецМесяца(Шапка.ПериодРегистрации)
             )
            );

Если ?(Стр.Emp_emptype = Null, 0, Стр.Emp_emptype) = 0 ИЛИ Условие() ИЛИ ?(Стр.Тест = Null, 1, Стр.Тест) = 2 Тогда
КонецЕсли;

Статус = ?(
      ПолучитьСкидку() = 0,
      "---",
      ?(ПолучитьСкидку() > 30, "Особый клиент", "Обычный клиент")
);
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL039"}) if d.code == "BSL039"]
        assert [(d.line - 1, d.character, d.end_line - 1, d.end_character) for d in diags] == [
            (2, 13, 8, 14),
            (11, 5, 11, 50),
            (11, 73, 11, 104),
            (17, 6, 17, 65),
        ]


# BSL041 — TestBsl041DeprecatedMessage
class TestBsl041DeprecatedMessage:
    def test_soobshchit_detected(self, tmp_path: Path) -> None:
        content = 'Сообщить("Готово");\n'
        diags = _check(content, tmp_path, select={"BSL041"})
        assert "BSL041" in _codes(diags)

    def test_message_detected(self, tmp_path: Path) -> None:
        content = 'Message("Done");\n'
        diags = _check(content, tmp_path, select={"BSL041"})
        assert "BSL041" in _codes(diags)

    def test_in_comment_not_flagged(self, tmp_path: Path) -> None:
        content = '// Сообщить("Готово")\n'
        diags = _check(content, tmp_path)
        assert "BSL041" not in _codes(diags)


# BSL042 — TestBsl042UnusedLocalMethod
class TestBsl042UnusedLocalMethod:
    def test_unused_local_method_detected(self, tmp_path: Path) -> None:
        content = """\
            Процедура НеИспользуется()
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL042"}) if d.code == "BSL042"]
        assert len(diags) == 1
        assert diags[0].message == _rule_msg("BSL042")

    def test_called_local_method_no_warning(self, tmp_path: Path) -> None:
        content = """\
            Процедура Используется()
            КонецПроцедуры

            Процедура Вызов() Экспорт
                Используется();
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL042"})
        assert "BSL042" not in _codes(diags)

    def test_export_method_no_warning(self, tmp_path: Path) -> None:
        content = """\
            Процедура ЭкспортныйМетод() Экспорт
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL042"})
        assert "BSL042" not in _codes(diags)

    def test_recursive_only_local_method_is_unused(self, tmp_path: Path) -> None:
        content = """\
            Процедура Рекурсия()
                Рекурсия();
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL042"}) if d.code == "BSL042"]
        assert len(diags) == 1
        assert diags[0].message == _rule_msg("BSL042")

    def test_extension_override_no_warning(self, tmp_path: Path) -> None:
        content = """\
            &Перед("Метод")
            Процедура Расширение()
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL042"})
        assert "BSL042" not in _codes(diags)

    def test_attachable_method_prefix_no_warning(self, tmp_path: Path) -> None:
        content = """\
            Процедура Подключаемый_Команда()
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL042"})
        assert "BSL042" not in _codes(diags)

    def test_attachable_method_prefix_en_no_warning(self, tmp_path: Path) -> None:
        content = """\
            Procedure Attachable_Command()
            EndProcedure
        """
        diags = _check(content, tmp_path, select={"BSL042"})
        assert "BSL042" not in _codes(diags)

    def test_form_module_is_skipped(self, tmp_path: Path) -> None:
        path = tmp_path / "Catalogs" / "Тест" / "Forms" / "Форма" / "Ext" / "Form" / "Module.bsl"
        path.parent.mkdir(parents=True)
        path.write_text(
            textwrap.dedent(
                """\
                Процедура ОбработчикФормы()
                КонецПроцедуры
                """
            ),
            encoding="utf-8",
        )
        diags = DiagnosticEngine(select={"BSL042"}).check_file(str(path))
        assert "BSL042" not in _codes(diags)

    def test_split_method_file_is_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "Configuration.xml").write_text("<Configuration/>", encoding="utf-8")
        path = tmp_path / "DataProcessors" / "Тест" / "Ext" / "РазрезанныйМетод.bsl"
        path.parent.mkdir(parents=True)
        path.write_text(
            textwrap.dedent(
                """\
                Процедура РазрезанныйМетод()
                КонецПроцедуры
                """
            ),
            encoding="utf-8",
        )
        diags = DiagnosticEngine(select={"BSL042"}).check_file(str(path))
        assert "BSL042" not in _codes(diags)

    def test_object_module_is_skipped_by_default(self, tmp_path: Path) -> None:
        path = tmp_path / "DataProcessors" / "Тест" / "Ext" / "ObjectModule.bsl"
        path.parent.mkdir(parents=True)
        path.write_text(
            textwrap.dedent(
                """\
                Процедура НеИспользуется()
                КонецПроцедуры
                """
            ),
            encoding="utf-8",
        )
        diags = DiagnosticEngine(select={"BSL042"}).check_file(str(path))
        assert "BSL042" not in _codes(diags)

    def test_managed_application_startup_handler_no_warning(self, tmp_path: Path) -> None:
        path = tmp_path / "Ext" / "ManagedApplicationModule.bsl"
        path.parent.mkdir(parents=True)
        path.write_text(
            textwrap.dedent(
                """\
                Процедура ПередНачаломРаботыСистемы(Отказ)
                КонецПроцедуры
                """
            ),
            encoding="utf-8",
        )
        diags = DiagnosticEngine(select={"BSL042"}).check_file(str(path))
        assert "BSL042" not in _codes(diags)


# BSL047 — TestBsl047MagicDate
class TestBsl047MagicDate:
    def test_magic_date_detected_in_expression(self, tmp_path: Path) -> None:
        content = 'День = Дата("00020101") + Шаг;\n'
        diags = _check(content, tmp_path, select={"BSL047"})
        assert "BSL047" in _codes(diags)

    def test_simple_assignment_no_warning(self, tmp_path: Path) -> None:
        content = "Конец = '12340101';\n"
        diags = _check(content, tmp_path, select={"BSL047"})
        assert "BSL047" not in _codes(diags)

    def test_bslls_fixture_magic_date_count(self, tmp_path: Path) -> None:
        content = """\
День = Дата("00020101");
День = Дата("00020101") + Шаг;
День = Дата("00020101121314") + Шаг;
День = '00010102' + Шаг;
Пока Сейчас < '12340101' Цикл
КонецЦикла;
Конец = '12340101';
День = Дата("00010101") + Шаг;
День = '0001-01why not?01' + Шаг;
День = '0001-01why not?02' + Шаг;
ИменаПараметров = СтроковыеФункции.РазложитьСтрокуВМассивПодстрок(ИмяПараметра, , Дата("00050101"));
ИменаПараметров = СтроковыеФункции.РазложитьСтрокуВМассивПодстрок(ИмяПараметра, "00050101", "00050101");
Настройки = Настройки('12350101');
Настройки.Свойство("00020501121314", ЗначениеЕдиничногоПараметра);
Выполнить("00020501121314" + '12350101');
ОтборЭлемента.ПравоеЗначение = Новый СтандартнаяДатаНачала(Дата('19800101000000'));
Значение = ?(А = '39990202', '39991231235959', '39990101000000');
Если Сейчас < Дата("12340101") Тогда
КонецЕсли;
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL047"}) if d.code == "BSL047"]
        assert len(diags) == 17


# BSL051 — TestBsl051UnreachableCode
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

    def test_code_after_break_continue_and_goto_detected(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Пока Истина Цикл
                    Прервать;
                    Сообщить("никогда");
                    Продолжить;
                    Сообщить("тоже никогда");
                КонецЦикла;
                Перейти ~Метка;
                Сообщить("после перейти");
                ~Метка:
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL051"}) if d.code == "BSL051"]
        assert [(d.line, d.character) for d in diags] == [
            (4, 8),
            (6, 8),
            (9, 4),
        ]

    def test_no_unreachable_code_no_warning(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Сообщить("привет");
                Возврат;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL051"})
        assert "BSL051" not in _codes(diags)

    def test_return_before_end_function_is_not_unreachable(self, tmp_path: Path) -> None:
        content = """\
            Функция Первый()
                Возврат 1;
            КонецФункции

            Функция Второй()
                Возврат 2;
            КонецФункции
        """
        diags = _check(content, tmp_path, select={"BSL051"})
        assert "BSL051" not in _codes(diags)

    def test_return_in_except_before_endtry_not_unreachable(self, tmp_path: Path) -> None:
        """КонецПопытки closes Попытка — not dead code after Возврат in Исключение."""
        content = """\
            Процедура Тест()
                Попытка
                    А = 1;
                Исключение
                    Возврат;
                КонецПопытки
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL051"})
        assert "BSL051" not in _codes(diags)

    def test_bsl051_uses_ast_delimiter_lines_when_tree_clean(self, tmp_path: Path) -> None:
        """Block delimiters come from tree-sitter keyword nodes, not only regex."""
        from onec_hbk_bsl.analysis.diagnostics import _bsl051_delimiter_lines_for_tree
        from onec_hbk_bsl.parser.bsl_parser import BslParser

        content = """\
            Процедура Тест()
                Попытка
                    А = 1;
                Исключение
                    Возврат;
                КонецПопытки
            КонецПроцедуры
        """
        tree = BslParser().parse_content(content)
        dlines = _bsl051_delimiter_lines_for_tree(tree)
        assert dlines is not None
        # Исключение / КонецПопытки (0-based)
        assert 3 in dlines
        assert 5 in dlines

    def test_dirty_tree_keeps_local_unreachable_detection(self, tmp_path: Path) -> None:
        from onec_hbk_bsl.parser.bsl_parser import BslParser

        content = """\
            Функция РаннийВыход()
                Результат = Ложь;
                Возврат Результат;

                Попытка
                    Результат = Истина;
                Исключение
                    Результат = Ложь;
                КонецПопытки;

                Возврат Результат;
            КонецФункции

            Процедура БитыйХвост()
                Если Истина Тогда
            КонецПроцедуры
        """
        tree = BslParser().parse_content(textwrap.dedent(content))
        assert tree.root_node.has_error

        diags = [d for d in _check(content, tmp_path, select={"BSL051"}) if d.code == "BSL051"]
        assert len(diags) == 1
        assert diags[0].line == 5

    def test_bslls_fixture_all_if_branches_return_makes_following_code_unreachable(
        self, tmp_path: Path
    ) -> None:
        content = """\
            Функция ДосрочныйВыход()
                Если А Тогда
                    Возврат 1;
                Иначе
                    Возврат 2;
                КонецЕсли;

                ТутОшибка = Истина;
            КонецФункции
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL051"}) if d.code == "BSL051"]
        assert len(diags) == 1
        assert diags[0].line == 8

    def test_unreachable_return_empty_string_excludes_semicolon(self, tmp_path: Path) -> None:
        content = """\
            Функция Тест()
                Возврат "";
                Возврат "";
            КонецФункции
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL051"}) if d.code == "BSL051"]
        assert len(diags) == 1
        assert diags[0].end_character == 14


# BSL052 — TestBsl052IdenticalExpressions
class TestBsl052IdenticalExpressions:
    def test_if_true_is_not_reported_as_identical_expressions(self, tmp_path: Path) -> None:
        content = """\
            Если Истина Тогда
                А = 1;
            КонецЕсли;
        """
        diags = _check(content, tmp_path, select={"BSL052"})
        assert "BSL052" not in _codes(diags)

    def test_if_false_is_not_reported_as_identical_expressions(self, tmp_path: Path) -> None:
        content = """\
            Если Ложь Тогда
                А = 1;
            КонецЕсли;
        """
        diags = _check(content, tmp_path, select={"BSL052"})
        assert "BSL052" not in _codes(diags)

    def test_normal_condition_no_warning(self, tmp_path: Path) -> None:
        content = """\
            Если А > 0 Тогда
                Б = 1;
            КонецЕсли;
        """
        diags = _check(content, tmp_path, select={"BSL052"})
        assert "BSL052" not in _codes(diags)

    def test_identical_binary_operands_detected(self, tmp_path: Path) -> None:
        content = """\
            Если Количество > Количество Тогда
                Сообщить(МояПеременная);
            КонецЕсли;
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL052"}) if d.code == "BSL052"]
        assert [(d.line, d.character, d.end_character, d.severity) for d in diags] == [
            (2, 5, 28, Severity.ERROR),
        ]
        assert diags[0].message == _rule_msg("BSL052")

    def test_addition_with_identical_operands_is_not_reported(self, tmp_path: Path) -> None:
        content = """\
            Если А + А Тогда
                Сообщить(МояПеременная);
            КонецЕсли;
        """
        diags = _check(content, tmp_path, select={"BSL052"})
        assert "BSL052" not in _codes(diags)

    def test_default_popular_divisors_are_not_reported(self, tmp_path: Path) -> None:
        content = """\
            Если 60 / 60 > 0 Тогда
                Сообщить(МояПеременная);
            КонецЕсли;
            Если 1024 / 1024 > 0 Тогда
                Сообщить(МояПеременная);
            КонецЕсли;
        """
        diags = _check(content, tmp_path, select={"BSL052"})
        assert "BSL052" not in _codes(diags)

    def test_non_popular_identical_divisor_is_reported(self, tmp_path: Path) -> None:
        content = """\
            Если 5 / 5 > 0 Тогда
                Сообщить(МояПеременная);
            КонецЕсли;
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL052"}) if d.code == "BSL052"]
        assert len(diags) == 1

    def test_transitive_logical_duplicate_detected(self, tmp_path: Path) -> None:
        content = """\
            Если А И Б И А Тогда
                Сообщить(МояПеременная);
            КонецЕсли;
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL052"}) if d.code == "BSL052"]
        assert len(diags) == 1

    def test_elseif_true_is_not_reported_as_identical_expressions(self, tmp_path: Path) -> None:
        content = """\
            Процедура Т()
                Если А = 1 Тогда
                ИначеЕсли Истина Тогда
                КонецЕсли;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL052"})
        assert "BSL052" not in _codes(diags)


# BSL054 — TestBsl054ModuleLevelVariable
class TestBsl054ModuleLevelVariable:
    def test_module_level_export_var_detected(self, tmp_path: Path) -> None:
        content = """\
            Перем МояПеременная Экспорт;
            Процедура Тест()
                Сообщить(МояПеременная);
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL054"})
        assert "BSL054" in _codes(diags)

    def test_module_level_export_vars_reported_per_variable(self, tmp_path: Path) -> None:
        content = """\
            Перем Первая, Вторая Экспорт;
            Процедура Тест()
                Сообщить(Первая);
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL054"}) if d.code == "BSL054"]
        assert [(d.line, d.character, d.end_character) for d in diags] == [
            (1, 6, 28),
            (1, 14, 28),
        ]

    def test_module_level_non_export_var_no_warning(self, tmp_path: Path) -> None:
        """Non-exported module-level Перем is not flagged (BSLLS ExportVariables only flags Экспорт)."""
        content = """\
            Перем МояПеременная;
            Процедура Тест()
                Сообщить(МояПеременная);
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL054"})
        assert "BSL054" not in _codes(diags)

    def test_local_var_no_warning(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Перем Локальная;
                Локальная = 1;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL054"})
        assert "BSL054" not in _codes(diags)


# BSL234 — TestBsl234QueryNestedFieldsByDot
class TestBsl234QueryNestedFieldsByDot:
    def test_query_nested_field_without_alias_reports(self, tmp_path: Path) -> None:
        content = """\
            Запрос = Новый Запрос(
            "ВЫБРАТЬ
            |   Таблица.Ссылка.Код
            |ИЗ
            |   Справочник.Номенклатура КАК Таблица");
        """
        diags = _check(content, tmp_path, select={"BSL234"})
        bsl234 = [d for d in diags if d.code == "BSL234"]
        assert len(bsl234) == 1
        assert bsl234[0].line == 3

    def test_bslls_fixture_virtual_table_parameters_report_each_nested_field(
        self, tmp_path: Path
    ) -> None:
        content = """\
            Запрос.Текст =
            "ВЫБРАТЬ
            |ИЗ
            |   РегистрНакопления.РасчетыСКлиентами.Обороты(
            |       &НачалоПериода,
            |       &КонецПериода,
            |       ,
            |       (АналитикаУчетаПоПартнерам.Партнер, АналитикаУчетаПоПартнерам.Контрагент, АналитикаУчетаПоПартнерам.Организация) В
            |           (ВЫБРАТЬ
            |               ВТ.Партнер КАК Партнер
            |            ИЗ
            |               ВТ КАК ВТ)) КАК Обороты";
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL234"}) if d.code == "BSL234"]
        assert [(d.line, d.character) for d in diags] == [(8, 9), (8, 44), (8, 82)]

    def test_bslls_fixture_cast_then_nested_field_reports_whole_expression(
        self, tmp_path: Path
    ) -> None:
        content = """\
            Запрос.Текст =
            "ВЫБРАТЬ
            |   ВЫРАЗИТЬ(ВТ_ПланОтгрузок.ДокументПлан КАК Документ.ЗаказКлиента).Валюта.Наценка КАК НаценкаВалютыДокумента
            |ИЗ
            |   ВТ_ПланОтгрузок КАК ВТ_ПланОтгрузок";
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL234"}) if d.code == "BSL234"]
        assert len(diags) == 1
        assert diags[0].line == 3
        assert diags[0].character == 4

    def test_business_process_metadata_source_is_not_nested_field(self, tmp_path: Path) -> None:
        content = """\
            Запрос.Текст =
            "ВЫБРАТЬ
            |   ДокументыЗаявки.Отпуск КАК Ссылка
            |ИЗ
            |   БизнесПроцесс.ЗаявкаСотрудникаОтпуск.Отпуска КАК ДокументыЗаявки";
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL234"}) if d.code == "BSL234"]
        assert diags == []

    def test_query_after_opening_quote_comment_reports_nested_field(self, tmp_path: Path) -> None:
        content = """\
            Результат = "
            // Комментарий перед запросом
            |ВЫБРАТЬ
            |   Таблица.Ссылка.Код КАК Код
            |ИЗ Справочник.Номенклатура КАК Таблица";
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL234"}) if d.code == "BSL234"]
        assert [(d.line, d.character) for d in diags] == [(4, 4)]

    def test_query_type_literal_is_not_nested_field(self, tmp_path: Path) -> None:
        content = """\
            Запрос.Текст =
            "ВЫБРАТЬ
            |   Источник.Ссылка
            |ИЗ
            |   РегистрСведений.Данные КАК Источник
            |ГДЕ
            |   ТИПЗНАЧЕНИЯ(Источник.Документ) В (ТИП(Документ.ЗаказКлиента))";
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL234"}) if d.code == "BSL234"]
        assert diags == []

    def test_fully_commented_query_is_ignored(self, tmp_path: Path) -> None:
        content = """\
            // Запрос = Новый Запрос(
            // "ВЫБРАТЬ
            // |   Таблица.Ссылка.Код КАК Код
            // |ИЗ Справочник.Номенклатура КАК Таблица"
            // );
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL234"}) if d.code == "BSL234"]
        assert diags == []


# BSL258 — TestBsl258UnionAll
class TestBsl258UnionAll:
    def test_union_without_all_inside_query_string_reports(self, tmp_path: Path) -> None:
        content = """\
            Запрос.Текст =
            "ВЫБРАТЬ
            |   Таблица.Ссылка КАК Ссылка
            |ИЗ
            |   Справочник.Номенклатура КАК Таблица
            |
            |ОБЪЕДИНИТЬ
            |
            |ВЫБРАТЬ
            |   Таблица.Ссылка КАК Ссылка
            |ИЗ
            |   Справочник.Номенклатура КАК Таблица";
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL258"}) if d.code == "BSL258"]
        assert len(diags) == 1
        assert diags[0].line == 7

    def test_union_all_is_clean(self, tmp_path: Path) -> None:
        content = """\
            Запрос.Текст =
            "ВЫБРАТЬ
            |   Таблица.Ссылка КАК Ссылка
            |ИЗ
            |   Справочник.Номенклатура КАК Таблица
            |
            |ОБЪЕДИНИТЬ ВСЕ
            |
            |ВЫБРАТЬ
            |   Таблица.Ссылка КАК Ссылка
            |ИЗ
            |   Справочник.Номенклатура КАК Таблица";
        """
        diags = _check(content, tmp_path, select={"BSL258"})
        assert "BSL258" not in _codes(diags)

    def test_union_separator_string_is_not_query_union(self, tmp_path: Path) -> None:
        content = """\
            Разделитель = " ОБЪЕДИНИТЬ ";
            ТекстЗапроса = СтрСоединить(ЧастиЗапроса, Разделитель);
        """
        diags = _check(content, tmp_path, select={"BSL258"})
        assert "BSL258" not in _codes(diags)

    def test_dynamic_union_fragment_start_is_clean(self, tmp_path: Path) -> None:
        content = """\
            ТекстЗапроса = ТекстЗапроса + "
            |
            |ОБЪЕДИНИТЬ
            |
            |ВЫБРАТЬ
            |   Таблица.Ссылка
            |ИЗ
            |   Справочник.Номенклатура КАК Таблица";
        """
        diags = _check(content, tmp_path, select={"BSL258"})
        assert "BSL258" not in _codes(diags)

    @pytest.mark.external_bslls
    def test_matches_bslls_fixture(self) -> None:
        fixture = (
            Path(".tmp/external-fixtures/bsl-language-server/src/test/resources/diagnostics")
            / "UnionAllDiagnostic.bsl"
        )
        if not fixture.exists():
            pytest.skip("BSLLS sources are not available")

        diags = [
            diag
            for diag in DiagnosticEngine(select={"BSL258"}).check_file(str(fixture))
            if diag.code == "BSL258"
        ]

        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (22, 5, 22, 15),
            (57, 5, 57, 15),
        ]
        assert {diag.severity for diag in diags} == {Severity.INFORMATION}
        assert {diag.message for diag in diags} == {
            "Замените конструкцию ОБЪЕДИНИТЬ на ОБЪЕДИНИТЬ ВСЕ"
        }


# BSL210 — TestBsl210LogicalOrInWhereSection
class TestBsl210LogicalOrInWhereSection:
    def test_multiline_where_with_two_or_detected(self, tmp_path: Path) -> None:
        content = """\
            ТекстЗапроса = "ВЫБРАТЬ
            |   Т.Ссылка
            |ИЗ
            |   Документ.РасходнаяНакладная КАК Т
            |ГДЕ
            |   Т.Проведен
            |   ИЛИ Т.ПометкаУдаления
            |   ИЛИ Т.Номер = 0
            |УПОРЯДОЧИТЬ ПО
            |   Т.Дата";
        """
        diags = _check(content, tmp_path, select={"BSL210"})
        bsl210 = [d for d in diags if d.code == "BSL210"]
        assert len(bsl210) == 2
        lines = sorted({d.line for d in bsl210})
        assert lines[0] + 1 == lines[1]

    def test_no_where_no_bsl210(self, tmp_path: Path) -> None:
        content = """\
            ТекстЗапроса = "ВЫБРАТЬ
            |   Код
            |ИЗ
            |   Справочник.Номенклатура";
        """
        diags = _check(content, tmp_path, select={"BSL210"})
        assert "BSL210" not in _codes(diags)

    def test_single_line_literal_or_in_where(self, tmp_path: Path) -> None:
        content = (
            'А = "ВЫБРАТЬ Ссылка ИЗ Документ.РасходнаяНакладная ГДЕ Номер = 1 ИЛИ Номер = 2";\n'
        )
        diags = _check(content, tmp_path, select={"BSL210"})
        assert _codes(diags).count("BSL210") == 1

    def test_escaped_quotes_do_not_end_multiline_query_literal(self, tmp_path: Path) -> None:
        content = """\
            ТекстЗапроса =
            "ВЫБРАТЬ
            |   Т.Ссылка
            |ИЗ
            |   Документ.РасходнаяНакладная КАК Т
            |ГДЕ
            |   Т.Номер В (""001"", ""002"")
            |   ИЛИ Т.Проведен";
        """
        diags = _check(content, tmp_path, select={"BSL210"})
        assert [(d.line, d.character, d.end_character) for d in diags if d.code == "BSL210"] == [
            (8, 4, 7),
        ]

    def test_blank_line_does_not_end_multiline_query_literal(self, tmp_path: Path) -> None:
        content = """\
            ТекстЗапроса = "ВЫБРАТЬ
            |   Т.Ссылка
            |ИЗ
            |   Документ.РасходнаяНакладная КАК Т

            |ГДЕ
            |   Т.Проведен
            |   ИЛИ Т.ПометкаУдаления";
        """
        diags = _check(content, tmp_path, select={"BSL210"})
        assert [(d.line, d.character, d.end_character) for d in diags if d.code == "BSL210"] == [
            (8, 4, 7),
        ]

    @pytest.mark.external_bslls
    def test_matches_bslls_fixture(self) -> None:
        fixture = Path(
            ".tmp/external-fixtures/bsl-language-server/src/test/resources/diagnostics/"
            "LogicalOrInTheWhereSectionOfQueryDiagnostic.bsl"
        )
        if not fixture.exists():
            pytest.skip("BSLLS fixture is not available")
        diags = [
            diag
            for diag in DiagnosticEngine(select={"BSL210"}).check_file(str(fixture))
            if diag.code == "BSL210"
        ]
        assert [(d.line, d.character, d.end_character) for d in diags] == [
            (8, 15, 18),
            (20, 8, 11),
            (32, 38, 41),
            (44, 8, 11),
            (45, 36, 39),
            (59, 21, 24),
        ]


# BSL060 — TestBsl060DoubleNegation
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


# BSL218 — TestBsl218MissingTemporaryFileDeletion
class TestBsl218MissingTemporaryFileDeletion:
    def test_bare_get_temp_file_name_is_reported(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                ПолучитьИмяВременногоФайла(".xml");
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL218"})
        assert _codes(diags) == ["BSL218"]

    def test_assigned_temp_without_deletion_is_reported(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Имя = ПолучитьИмяВременногоФайла(".xml");
                Сообщить(Имя);
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL218"})
        assert _codes(diags) == ["BSL218"]

    def test_delete_files_afterwards_is_clean(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Имя = ПолучитьИмяВременногоФайла(".xml");
                УдалитьФайлы(Имя);
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL218"})
        assert "BSL218" not in _codes(diags)

    def test_get_temp_file_name_english_alias(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Имя = GetTempFileName(".xml");
                DeleteFiles(Имя);
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL218"})
        assert "BSL218" not in _codes(diags)

    def test_move_file_satisfies_rule(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Имя = ПолучитьИмяВременногоФайла(".xml");
                ПереместитьФайл(Имя, "куда");
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL218"})
        assert "BSL218" not in _codes(diags)

    def test_deletion_only_in_same_branch_counts(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Если Истина Тогда
                    Имя = ПолучитьИмяВременногоФайла(".xml");
                КонецЕсли;
                УдалитьФайлы(Имя);
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL218"})
        assert _codes(diags) == ["BSL218"]

    def test_module_level_with_deletion_is_clean(self, tmp_path: Path) -> None:
        content = """\
            Имя = ПолучитьИмяВременногоФайла(".xml");
            УдалитьФайлы(Имя);
        """
        diags = _check(content, tmp_path, select={"BSL218"})
        assert "BSL218" not in _codes(diags)

    def test_qualified_delete_does_not_satisfy_like_bslls_default(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Имя = ПолучитьИмяВременногоФайла(".xml");
                ОбщегоНазначения.УдалитьФайлы(Имя);
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL218"})
        assert _codes(diags) == ["BSL218"]

    @pytest.mark.external_bslls
    def test_matches_bslls_fixture(self) -> None:
        fixture = (
            Path(".tmp/external-fixtures/bsl-language-server/src/test/resources/diagnostics")
            / "MissingTemporaryFileDeletionDiagnostic.bsl"
        )
        if not fixture.exists():
            pytest.skip("BSLLS sources are not available")

        diags = [
            diag
            for diag in DiagnosticEngine(select={"BSL218"}).check_file(str(fixture))
            if diag.code == "BSL218"
        ]

        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (7, 29, 7, 62),
            (20, 30, 20, 63),
            (26, 30, 26, 63),
            (46, 29, 46, 62),
            (50, 30, 50, 63),
            (65, 30, 65, 58),
            (72, 26, 72, 54),
        ]
        assert {diag.severity for diag in diags} == {Severity.ERROR}
        assert {diag.message for diag in diags} == {
            "Нужно добавить удаление временного файла после использования"
        }


# BSL225 — TestBsl225NumberOfValuesInStructureConstructor
class TestBsl225NumberOfValuesInStructureConstructor:
    def test_structure_with_too_many_values_is_reported(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Данные = Новый Структура("Ключ1,Ключ2,Ключ3,Ключ4", 1, 2, 3, 4);
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL225"})
        assert _codes(diags) == ["BSL225"]
        assert diags[0].message == _rule_msg("BSL225")

    def test_structure_with_three_values_is_clean(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Данные = Новый Структура("Ключ1,Ключ2,Ключ3", 1, 2, 3);
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL225"})
        assert "BSL225" not in _codes(diags)

    def test_fixed_structure_with_too_many_values_is_reported(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Данные = Новый ФиксированнаяСтруктура("К1,К2,К3,К4", 1, 2, 3, 4);
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL225"}) if d.code == "BSL225"]
        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (2, 13, 2, 68)
        ]
        assert diags[0].severity is Severity.INFORMATION
        assert diags[0].message == _rule_msg("BSL225")


# BSL245 — TestBsl245ServerSideExportFormMethod
class TestBsl245ServerSideExportFormMethod:
    @staticmethod
    def _write_form_xml(path: Path, *, managed: bool = True) -> None:
        xml_path = path.parent.parent / "Form.xml"
        xml_path.write_text(
            (
                "<Form><Properties>"
                f"<FormType>{'Managed' if managed else 'Ordinary'}</FormType>"
                f"<UseManagedForm>{str(managed).lower()}</UseManagedForm>"
                "</Properties></Form>"
            ),
            encoding="utf-8",
        )

    def test_server_export_in_form_module_is_reported(self, tmp_path: Path) -> None:
        content = """\
            &НаСервере
            Процедура ПолучитьДанные() Экспорт
            КонецПроцедуры
        """
        path = tmp_path / "Forms" / "ФормаСписка" / "Ext" / "Form" / "Module.bsl"
        path.parent.mkdir(parents=True)
        path.write_text(textwrap.dedent(content), encoding="utf-8")
        self._write_form_xml(path)
        diags = DiagnosticEngine(select={"BSL245"}).check_file(str(path))
        assert _codes(diags) == ["BSL245"]
        assert diags[0].severity == Severity.ERROR

    def test_client_export_in_form_module_is_clean(self, tmp_path: Path) -> None:
        content = """\
            &НаКлиенте
            Процедура ПолучитьДанные() Экспорт
            КонецПроцедуры
        """
        path = tmp_path / "Forms" / "ФормаСписка" / "Ext" / "Form" / "Module.bsl"
        path.parent.mkdir(parents=True)
        path.write_text(textwrap.dedent(content), encoding="utf-8")
        self._write_form_xml(path)
        diags = DiagnosticEngine(select={"BSL245"}).check_file(str(path))
        assert "BSL245" not in _codes(diags)

    def test_server_export_in_ordinary_ext_module_is_clean(self, tmp_path: Path) -> None:
        content = """\
            Процедура ЗавершитьПолучение(Результат, ДополнительныеПараметры) Экспорт
            КонецПроцедуры
        """
        path = tmp_path / "Forms" / "ФормаСписка" / "Ext" / "Module.bsl"
        path.parent.mkdir(parents=True)
        path.write_text(textwrap.dedent(content), encoding="utf-8")
        diags = DiagnosticEngine(select={"BSL245"}).check_file(str(path))
        assert "BSL245" not in _codes(diags)

    def test_notify_description_export_callback_in_managed_form_still_reports(
        self, tmp_path: Path
    ) -> None:
        content = """\
            &НаКлиенте
            Процедура ЗапуститьПолучение()
                Оповещение = Новый ОписаниеОповещения("ЗавершитьПолучение", ЭтаФорма);
            КонецПроцедуры

            Процедура ЗавершитьПолучение(Результат, ДополнительныеПараметры) Экспорт
            КонецПроцедуры
        """
        path = tmp_path / "Forms" / "ФормаСписка" / "Ext" / "Form" / "Module.bsl"
        path.parent.mkdir(parents=True)
        path.write_text(textwrap.dedent(content), encoding="utf-8")
        self._write_form_xml(path)
        diags = DiagnosticEngine(select={"BSL245"}).check_file(str(path))
        assert _codes(diags) == ["BSL245"]

    def test_server_export_in_form_module_without_metadata_is_clean(self, tmp_path: Path) -> None:
        content = """\
            &НаСервере
            Процедура ПолучитьДанные() Экспорт
            КонецПроцедуры
        """
        path = tmp_path / "Forms" / "ФормаСписка" / "Ext" / "Form" / "Module.bsl"
        path.parent.mkdir(parents=True)
        path.write_text(textwrap.dedent(content), encoding="utf-8")
        diags = DiagnosticEngine(select={"BSL245"}).check_file(str(path))
        assert "BSL245" not in _codes(diags)

    def test_object_module_split_with_form_substring_is_clean(self, tmp_path: Path) -> None:
        content = """\
            Функция ФайлыИнформационнойБазы_ДоступноДобавление() Экспорт
                Возврат Истина;
            КонецФункции
        """
        path = (
            tmp_path
            / "DataProcessors"
            / "ТестЭДО"
            / "Ext"
            / "ФайлыИнформационнойБазы_ДоступноДобавление.bsl"
        )
        path.parent.mkdir(parents=True)
        path.write_text(textwrap.dedent(content), encoding="utf-8")
        diags = DiagnosticEngine(select={"BSL245"}).check_file(str(path))
        assert "BSL245" not in _codes(diags)

    def test_server_export_in_split_form_fragment_is_clean(self, tmp_path: Path) -> None:
        content = """\
            &НаСервере
            Процедура ПолучитьДанные() Экспорт
            КонецПроцедуры
        """
        form_dir = tmp_path / "Forms" / "ФормаСписка" / "Ext" / "Form"
        form_dir.mkdir(parents=True)
        (form_dir / "Module.bsl").write_text("// full module\n", encoding="utf-8")
        path = form_dir / "ПолучитьДанные.bsl"
        path.write_text(textwrap.dedent(content), encoding="utf-8")
        diags = DiagnosticEngine(select={"BSL245"}).check_file(str(path))
        assert "BSL245" not in _codes(diags)

    def test_server_export_in_split_form_layout_module_is_clean(self, tmp_path: Path) -> None:
        content = """\
            &НаСервере
            Процедура ПолучитьДанные() Экспорт
            КонецПроцедуры
        """
        path = tmp_path / "Forms" / "ФормаСписка" / "Ext" / "Form" / "Module.bsl"
        path.parent.mkdir(parents=True)
        path.write_text(textwrap.dedent(content), encoding="utf-8")
        (path.parent / "Module.header").write_text("", encoding="utf-8")
        self._write_form_xml(path)
        diags = DiagnosticEngine(select={"BSL245"}).check_file(str(path))
        assert "BSL245" not in _codes(diags)


# BSL064 — TestBsl064ProcedureReturnsValue
class TestBsl064ProcedureReturnsValue:
    def test_procedure_with_return_value_detected(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Возврат 42;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL064"})
        assert "BSL064" in _codes(diags)

    def test_each_procedure_return_value_reported_bslls_parity(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Если Условие Тогда
                    Возврат 1;
                КонецЕсли;
                Возврат 2;
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL064"}) if d.code == "BSL064"]
        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (3, 8, 3, 18),
            (5, 4, 5, 14),
        ]

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


# BSL065 — TestBsl065MissingReturnedValueDescription
class TestBsl065MissingReturnedValueDescription:
    def test_function_without_return_description_detected(self, tmp_path: Path) -> None:
        content = """\
            // Описание функции
            Функция Тест()
                А = 1;
            КонецФункции
        """
        diags = _check(content, tmp_path, select={"BSL065"})
        assert "BSL065" in _codes(diags)

    def test_function_with_return_description_no_warning(self, tmp_path: Path) -> None:
        content = """\
            // Описание функции
            // Возвращаемое значение:
            //   Число - результат
            Функция Тест()
                А = 1;
                Возврат 1;
            КонецФункции
        """
        diags = _check(content, tmp_path, select={"BSL065"})
        assert "BSL065" not in _codes(diags)

    def test_function_with_structured_return_description_no_warning(self, tmp_path: Path) -> None:
        content = """\
            // Описание функции
            // Возвращаемое значение:
            //  Неопределено, ТаблицаЗначений - таблица остатков:
            //    * Количество - Число - остаток количества
            Функция Тест()
                Возврат Новый ТаблицаЗначений;
            КонецФункции
        """
        diags = _check(content, tmp_path, select={"BSL065"})
        assert "BSL065" not in _codes(diags)

    def test_short_return_description_is_valid_by_default(self, tmp_path: Path) -> None:
        content = """\
            // Описание функции
            // Возвращаемое значение:
            // Строка
            Функция Тест()
                Возврат "";
            КонецФункции
        """
        diags = _check(content, tmp_path, select={"BSL065"})
        assert "BSL065" not in _codes(diags)

    def test_inline_return_description_is_valid(self, tmp_path: Path) -> None:
        content = """\
            // Описание функции
            //
            // Возвращаемое значение - Булево - Истина, если значение подходит.
            //
            Функция Тест()
                Возврат Истина;
            КонецФункции
        """
        diags = _check(content, tmp_path, select={"BSL065"})
        assert "BSL065" not in _codes(diags)

    def test_type_only_return_description_with_period_is_not_valid(self, tmp_path: Path) -> None:
        content = """\
            // Описание функции
            //
            // Возвращаемое значение:
            //  Булево.
            //
            Функция Тест()
                Возврат Истина;
            КонецФункции
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL065"}) if d.code == "BSL065"]
        assert len(diags) == 1

    def test_legacy_return_description_with_tabs_is_valid(self, tmp_path: Path) -> None:
        path = tmp_path / "ObjectModule.bsl"
        content = """\
            // Описание функции
            //
            // Возвращаемое значение:
            //\t Массив\t- Массив строк
            //
            Функция Тест() Экспорт
                Возврат Новый Массив;
            КонецФункции
        """
        path.write_text(textwrap.dedent(content), encoding="utf-8")
        diags = DiagnosticEngine(select={"BSL065"}).check_file(path)
        assert "BSL065" not in _codes(diags)

    def test_legacy_return_description_dash_bullet_is_valid(self, tmp_path: Path) -> None:
        path = tmp_path / "ObjectModule.bsl"
        content = """\
            // Описание функции
            //
            // Возвращаемое значение:
            //   - Структура
            //
            Функция Тест() Экспорт
                Возврат Новый Структура;
            КонецФункции
        """
        path.write_text(textwrap.dedent(content), encoding="utf-8")
        diags = DiagnosticEngine(select={"BSL065"}).check_file(path)
        assert "BSL065" not in _codes(diags)

    def test_legacy_return_description_structure_space_before_colon_is_valid(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "ObjectModule.bsl"
        content = """\
            // Описание функции
            //
            // Возвращаемое значение:
            //  Структура :
            //   * Имя - Строка - имя
            //
            Функция Тест() Экспорт
                Возврат Новый Структура;
            КонецФункции
        """
        path.write_text(textwrap.dedent(content), encoding="utf-8")
        diags = DiagnosticEngine(select={"BSL065"}).check_file(path)
        assert "BSL065" not in _codes(diags)

    def test_legacy_return_description_array_of_custom_type_with_period_is_valid(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "ObjectModule.bsl"
        content = """\
            // Описание функции
            //
            // Возвращаемое значение:
            //  Массив из НовыйОшибкаВалидации.
            //
            Функция Тест() Экспорт
                Возврат Новый Массив;
            КонецФункции
        """
        path.write_text(textwrap.dedent(content), encoding="utf-8")
        diags = DiagnosticEngine(select={"BSL065"}).check_file(path)
        assert "BSL065" not in _codes(diags)

    def test_procedure_with_return_description_reports_removal(self, tmp_path: Path) -> None:
        content = """\
            // Описание процедуры
            // Возвращаемое значение:
            // Строка - описание
            Процедура Тест()
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL065"}) if d.code == "BSL065"]
        assert len(diags) == 1
        assert diags[0].message == _rule_msg("BSL065")

    def test_function_with_return_description_before_directive(self, tmp_path: Path) -> None:
        """Doc block may be separated from declaration by compiler directives."""
        content = """\
            // Описание функции
            // Возвращаемое значение:
            //   Число - результат
            &НаКлиенте
            Функция Тест()
                А = 1;
                Возврат 1;
            КонецФункции
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

    def test_form_module_path_skips_bsl065(self, tmp_path: Path) -> None:
        """BSLLS parity: EDT form ``Module.bsl`` — skip Missing export comment."""
        content = """\
            Процедура Тест() Экспорт
                А = 1;
            КонецПроцедуры
        """
        form_dir = tmp_path / "Forms" / "SomeForm" / "Ext"
        form_dir.mkdir(parents=True)
        bsl_path = form_dir / "Module.bsl"
        bsl_path.write_text(textwrap.dedent(content), encoding="utf-8")
        diags = DiagnosticEngine(select={"BSL065"}).check_file(str(bsl_path))
        assert "BSL065" not in _codes(diags)

    def test_notify_completion_export_no_bsl065(self, tmp_path: Path) -> None:
        """Экспорт *Завершение на клиенте — штатный колбэк; отдельный // к экспорту не обязателен."""
        content = """\
            &НаКлиенте
            Процедура ДействиеЗавершение(Результат, Параметры) Экспорт
                А = Результат;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL065"})
        assert "BSL065" not in _codes(diags)


# BSL066 — TestBsl066DeprecatedFind
class TestBsl066DeprecatedFind:
    def test_najti_detected(self, tmp_path: Path) -> None:
        """Глобальный вызов Найти() флагуется — устаревшая строковая функция."""
        content = 'Поз = Найти(Строка, "текст");\n'
        diags = _check(content, tmp_path, select={"BSL066"})
        assert "BSL066" in _codes(diags)

    def test_array_najti_not_flagged(self, tmp_path: Path) -> None:
        """МойМассив.Найти() — метод объекта, не глобальная функция — не флагуется."""
        content = "Элемент = МойМассив.Найти(Значение);\n"
        diags = _check(content, tmp_path, select={"BSL066"})
        assert "BSL066" not in _codes(diags)

    def test_chained_object_najti_not_flagged(self, tmp_path: Path) -> None:
        content = (
            'Если Документ.Метаданные().ТабличныеЧасти.Найти("Виды").Реквизиты.Найти("Сумма") '
            "= Неопределено Тогда\nКонецЕсли;\n"
        )
        diags = _check(content, tmp_path, select={"BSL066"})
        assert "BSL066" not in _codes(diags)

    def test_in_comment_no_warning(self, tmp_path: Path) -> None:
        content = '// Найти("текст");\n'
        diags = _check(content, tmp_path, select={"BSL066"})
        assert "BSL066" not in _codes(diags)

    def test_strfind_no_warning(self, tmp_path: Path) -> None:
        """СтрНайти() — современная замена, не флагуется."""
        content = 'Поз = СтрНайти(Строка, "текст");\n'
        diags = _check(content, tmp_path, select={"BSL066"})
        assert "BSL066" not in _codes(diags)

    def test_vreg_nreg_not_deprecated(self, tmp_path: Path) -> None:
        """Врег/НРег — текущие платформенные функции, не устаревшие."""
        content = "Рез = Врег(Строка) + НРег(Другая);\n"
        diags = _check(content, tmp_path, select={"BSL066"})
        assert "BSL066" not in _codes(diags)

    def test_sokr_functions_not_deprecated(self, tmp_path: Path) -> None:
        """СокрЛ/СокрП/СокрЛП — текущие платформенные функции, не устаревшие."""
        content = "Рез = СокрЛП(СокрЛ(СокрП(Строка)));\n"
        diags = _check(content, tmp_path, select={"BSL066"})
        assert "BSL066" not in _codes(diags)

    def test_soobshchit_not_bsl066(self, tmp_path: Path) -> None:
        """Сообщить() — не BSL066 (DeprecatedFind), это DeprecatedMessage."""
        content = 'Сообщить("Привет");\n'
        diags = _check(content, tmp_path, select={"BSL066"})
        assert "BSL066" not in _codes(diags)


# BSL097 — TestBsl097DeprecatedCurrentDate
class TestBsl097DeprecatedCurrentDate:
    def test_current_date_detected(self, tmp_path: Path) -> None:
        content = "Дата = ТекущаяДата();\n"
        diags = _check(content, tmp_path, select={"BSL097"})
        assert "BSL097" in _codes(diags)

    def test_english_current_date_detected(self, tmp_path: Path) -> None:
        content = "DateValue = CurrentDate();\n"
        diags = _check(content, tmp_path, select={"BSL097"})
        assert "BSL097" in _codes(diags)

    def test_object_method_not_flagged(self, tmp_path: Path) -> None:
        content = "Дата = Объект.ТекущаяДата();\n"
        diags = _check(content, tmp_path, select={"BSL097"})
        assert "BSL097" not in _codes(diags)

    def test_comment_and_string_not_flagged(self, tmp_path: Path) -> None:
        content = """\
            // ТекущаяДата();
            Текст = "CurrentDate()";
        """
        diags = _check(content, tmp_path, select={"BSL097"})
        assert "BSL097" not in _codes(diags)

    def test_current_session_date_not_flagged(self, tmp_path: Path) -> None:
        content = "Дата = ТекущаяДатаСеанса();\n"
        diags = _check(content, tmp_path, select={"BSL097"})
        assert "BSL097" not in _codes(diags)


# BSL153, BSL202, BSL205, BSL221, BSL222, BSL223, BSL239, BSL243, BSL249, BSL265, BSL271, BSL276 — TestAdditionalParityBatch
class TestAdditionalParityBatch:
    def test_bsl202_strtemplate_mismatch_detected(self, tmp_path: Path) -> None:
        diags = _check('СтрШаблон("%1 %2", Значение);\n', tmp_path, select={"BSL202"})
        assert "BSL202" in _codes(diags)

    def test_bsl205_isinrole_detected(self, tmp_path: Path) -> None:
        diags = _check(
            'Если РольДоступна("ПолныеПрава") Тогда\nКонецЕсли;\n',
            tmp_path,
            select={"BSL205"},
        )
        assert "BSL205" in _codes(diags)

    def test_bsl223_nested_structure_ctor_detected(self, tmp_path: Path) -> None:
        diags = _check(
            'А = Новый Структура("Ключ, Значение", Новый Структура("Вложенный, Значение", 1));\n',
            tmp_path,
            select={"BSL223"},
        )
        assert "BSL223" in _codes(diags)

    def test_bsl223_single_argument_nested_constructor_detected(self, tmp_path: Path) -> None:
        content = 'А = Новый Структура("Тип", Новый ОписаниеТипов("Строка"));\n'
        diags = _check(content, tmp_path, select={"BSL223"})
        bsl223 = [diag for diag in diags if diag.code == "BSL223"]
        assert [(diag.line, diag.character, diag.end_character) for diag in bsl223] == [(1, 4, 57)]

    def test_bsl223_parameterless_nested_constructor_is_clean(self, tmp_path: Path) -> None:
        content = 'А = Новый Структура("Массив", Новый Массив);\n'
        diags = _check(content, tmp_path, select={"BSL223"})
        assert "BSL223" not in _codes(diags)

    def test_bsl243_self_insertion_detected(self, tmp_path: Path) -> None:
        diags = _check("Массив.Добавить(Массив);\n", tmp_path, select={"BSL243"})
        assert "BSL243" in _codes(diags)

    def test_bsl243_dotted_receiver_tail_match_is_clean(self, tmp_path: Path) -> None:
        diags = _check("Объект.Массив.Добавить(Массив);\n", tmp_path, select={"BSL243"})
        assert "BSL243" not in _codes(diags)

    def test_bsl243_dotted_receiver_self_insertion_detected(self, tmp_path: Path) -> None:
        diags = _check("Объект.Массив.Добавить(Объект.Массив);\n", tmp_path, select={"BSL243"})
        bsl243 = [diag for diag in diags if diag.code == "BSL243"]
        assert [(diag.line, diag.character, diag.end_character) for diag in bsl243] == [(1, 0, 13)]

    def test_bsl249_style_constructor_detected(self, tmp_path: Path) -> None:
        diags = _check("ЦветФона = Новый Цвет(255, 0, 0);\n", tmp_path, select={"BSL249"})
        bsl249 = [d for d in diags if d.code == "BSL249"]
        assert len(bsl249) == 1
        assert bsl249[0].character == 11
        assert bsl249[0].severity is Severity.ERROR
        assert bsl249[0].message == _rule_msg("BSL249")

    def test_bsl249_uses_bslls_constructor_set(self, tmp_path: Path) -> None:
        diags = _check("Значение = Новый Кисть();\n", tmp_path, select={"BSL249"})
        assert "BSL249" not in _codes(diags)

    def test_bsl265_bslls_useless_ternary_fixture_count(self, tmp_path: Path) -> None:
        content = """\
// Бессмысленные тернарники
А = ?(Б = 1, Истина, Ложь);
А = ?(Б = 0, False, True);
А = ?(Б = 1, True, Истина);
А = ?(Б = 0, Ложь, False);
А = ?(истина, 1, 0);
А = ?(false, 0, 1);

А = ?(Б = 1, True, 1);
А = ?(Б = 0, 0, False);
БулевоЗначение = ?(ЗначениеЗаполнено(СсылкаНаСправочник), СсылкаНаСправочник.БулевоПоле, Ложь);
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL265"}) if d.code == "BSL265"]
        assert len(diags) == 6

    def test_bsl153_flags_uppercase_structural_keyword(self, tmp_path: Path) -> None:
        diags = _check(
            "Для Каждого СтрокаТаблицы ИЗ ТаблицаПолучателей Цикл\nКонецЦикла;\n",
            tmp_path,
            select={"BSL153"},
        )
        bsl153 = [d for d in diags if d.code == "BSL153"]
        assert len(bsl153) == 1
        assert bsl153[0].character == 26
        assert bsl153[0].message == _rule_msg("BSL153")

    def test_bsl221_missing_declared_language_detected(self, tmp_path: Path) -> None:
        diags = _check("Сообщение = НСтр(\"en = 'Done'\");\n", tmp_path, select={"BSL221"})
        assert "BSL221" in _codes(diags)

    def test_bsl221_all_declared_languages_is_clean(self, tmp_path: Path) -> None:
        path = tmp_path / "test.bsl"
        path.write_text("Сообщение = НСтр(\"ru = 'Готово'; en = 'Done'\");\n", encoding="utf-8")

        diags = DiagnosticEngine(select={"BSL221"}, declared_languages="ru,en").check_file(
            str(path)
        )
        assert "BSL221" not in _codes(diags)

    def test_bsl222_nstr_inside_template_detected(self, tmp_path: Path) -> None:
        diags = _check(
            'Сообщение = СтрШаблон("%1", НСтр("en = \'Done\'"));\n',
            tmp_path,
            select={"BSL222"},
        )
        assert "BSL222" in _codes(diags)

    def test_bsl239_reserved_parameter_names_detected(self, tmp_path: Path) -> None:
        content = "Процедура Тест(Дата)\nКонецПроцедуры\n"
        p = tmp_path / "test.bsl"
        p.write_text(content, encoding="utf-8")
        from onec_hbk_bsl.analysis.diagnostics import DiagnosticEngine

        diags = DiagnosticEngine(
            select={"BSL239"},
            reserved_parameter_names_pattern="Дата|Date",
        ).check_file(str(p))
        assert "BSL239" in [d.code for d in diags]

    def _bsl271_domain_diags(self, content: str) -> list[Diagnostic]:
        from onec_hbk_bsl.analysis import diagnostics as diagnostics_module
        from onec_hbk_bsl.analysis.lsp_positions import utf8_byte_offset_to_lsp_character
        from onec_hbk_bsl.parser.bsl_parser import BslParser

        return ModuleModel(
            "DataProcessors/Test/Ext/ObjectModule.bsl"
        ).validate_bsl221_222_239_271_light_pool(
            lines=textwrap.dedent(content).splitlines(),
            tree=BslParser().parse_content(textwrap.dedent(content)),
            procs=[],
            enabled=("BSL271",),
            snapshot=None,
            strip_inline_comment_preserve_strings_fn=diagnostics_module._strip_inline_comment_preserve_strings,
            reserved_parameter_names_re=None,
            ts_walk_fn=diagnostics_module._ts_walk,
            ts_child_of_type_fn=diagnostics_module._ts_child_of_type,
            ts_node_text_fn=diagnostics_module._ts_node_text,
            utf8_byte_offset_to_lsp_character_fn=utf8_byte_offset_to_lsp_character,
            bsl221_nstr_re=diagnostics_module._RE_BSL221_NSTR,
            bsl221_lang_re=diagnostics_module._RE_BSL221_LANG,
            bsl271_unix_unavailable_new_re=diagnostics_module._RE_BSL271_UNIX_UNAVAILABLE_NEW,
            bsl271_platform_guard_re=diagnostics_module._RE_BSL271_PLATFORM_GUARD,
            proc_name_span_fn=diagnostics_module._proc_name_span,
            declared_languages=set(),
        )

    def test_bsl271_unix_unavailable_object_detected(self) -> None:
        content = """\
            Процедура Тест()
                Компонента = Новый COMОбъект("Excel.Application");
            КонецПроцедуры
        """
        bsl271 = [d for d in self._bsl271_domain_diags(content) if d.code == "BSL271"]
        line = textwrap.dedent(content).splitlines()[1]
        assert [(d.line, d.character, d.end_line, d.end_character) for d in bsl271] == [
            (2, line.index("Новый"), 2, line.index(";"))
        ]

    def test_bsl271_unix_unavailable_object_guarded_by_platform_is_clean(self) -> None:
        content = """\
            Если ТипПлатформы() = ТипПлатформы.Windows Тогда
                Компонента = Новый COMОбъект("Excel.Application");
            КонецЕсли;
        """
        diags = self._bsl271_domain_diags(content)

        assert "BSL271" not in _codes(diags)

    def test_bsl276_proceed_with_call_without_annotation_detected(self, tmp_path: Path) -> None:
        diags = _check(
            "Процедура Тест()\n    ПродолжитьВызов();\nКонецПроцедуры\n",
            tmp_path,
            select={"BSL276"},
        )
        assert "BSL276" in _codes(diags)


# BSL255 — TestBsl255TryNumber
class TestBsl255TryNumber:
    def test_number_call_inside_try_reports(self, tmp_path: Path) -> None:
        content = """\
            Попытка
                Значение = Число(Текст);
            Исключение
            КонецПопытки;
        """
        diags = _check(content, tmp_path, select={"BSL255"})

        assert [(d.line, d.character, d.end_character) for d in diags if d.code == "BSL255"] == [
            (2, 15, 27),
        ]

    def test_number_call_in_except_is_clean(self, tmp_path: Path) -> None:
        content = """\
            Попытка
            Исключение
                Значение = Число(Текст);
            КонецПопытки;
        """

        assert "BSL255" not in _codes(_check(content, tmp_path, select={"BSL255"}))

    @pytest.mark.external_bslls
    def test_matches_bslls_fixture(self) -> None:
        fixture = (
            Path(".tmp/external-fixtures/bsl-language-server/src/test/resources/diagnostics")
            / "TryNumberDiagnostic.bsl"
        )
        if not fixture.exists():
            pytest.skip("BSLLS fixture is not available")

        diags = [
            d
            for d in DiagnosticEngine(select={"BSL255"}).check_file(str(fixture))
            if d.code == "BSL255"
        ]

        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (9, 4, 9, 12),
            (10, 4, 10, 13),
            (13, 8, 13, 17),
        ]
        assert {d.severity for d in diags} == {Severity.WARNING}
        assert {d.message for d in diags} == {
            "Не следует использовать исключения для приведения значения к типу"
        }


# BSL257 — TestBsl257UnaryPlusInConcatenation
class TestBsl257UnaryPlusInConcatenation:
    def test_unary_plus_after_concat_reports(self, tmp_path: Path) -> None:
        content = 'Текст = "A" + +Значение;\n'
        diags = _check(content, tmp_path, select={"BSL257"})

        assert [(d.line, d.character, d.end_character) for d in diags if d.code == "BSL257"] == [
            (1, 14, 15),
        ]

    def test_unary_plus_number_after_concat_is_clean(self, tmp_path: Path) -> None:
        content = "Значение = 1 + +1;\n"

        assert "BSL257" not in _codes(_check(content, tmp_path, select={"BSL257"}))

    @pytest.mark.external_bslls
    def test_matches_bslls_fixture(self) -> None:
        fixture = (
            Path(".tmp/external-fixtures/bsl-language-server/src/test/resources/diagnostics")
            / "UnaryPlusInConcatenationDiagnostic.bsl"
        )
        if not fixture.exists():
            pytest.skip("BSLLS fixture is not available")

        diags = [
            diag
            for diag in DiagnosticEngine(select={"BSL257"}).check_file(str(fixture))
            if diag.code == "BSL257"
        ]

        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (6, 20, 6, 21),
            (9, 33, 9, 34),
            (24, 21, 24, 22),
        ]
        assert {diag.severity for diag in diags} == {Severity.ERROR}
        assert {diag.message for diag in diags} == {
            "Унарный плюс в конкатенации строк потенциально приводит к ошибке времени выполнения"
        }


# BSL273 — TestBsl273VirtualTableCallWithoutParameters
class TestBsl273VirtualTableCallWithoutParameters:
    def test_empty_virtual_table_parameters_report_exact_range(self, tmp_path: Path) -> None:
        content = (
            "Процедура Тест()\n"
            '    Запрос = Новый Запрос("ВЫБРАТЬ * ИЗ '
            'РегистрНакопления.Товары.Остатки() КАК Остатки");\n'
            "КонецПроцедуры\n"
        )

        diags = [d for d in _check(content, tmp_path, select={"BSL273"}) if d.code == "BSL273"]

        assert [
            (d.line, d.character, d.end_line, d.end_character, d.severity, d.message) for d in diags
        ] == [(2, 40, 2, 74, Severity.ERROR, _rule_msg("BSL273"))]

    def test_parameterized_virtual_table_is_clean(self, tmp_path: Path) -> None:
        content = (
            "Процедура Тест()\n"
            '    Запрос = Новый Запрос("ВЫБРАТЬ * ИЗ '
            'РегистрНакопления.Товары.Остатки(&Дата) КАК Остатки");\n'
            "КонецПроцедуры\n"
        )

        assert "BSL273" not in _codes(_check(content, tmp_path, select={"BSL273"}))

    @pytest.mark.external_bslls
    def test_matches_bslls_fixture(self) -> None:
        fixture = (
            Path(".tmp/external-fixtures/bsl-language-server/src/test/resources/diagnostics")
            / "VirtualTableCallWithoutParametersDiagnostic.bsl"
        )
        if not fixture.exists():
            pytest.skip("BSLLS fixture is not available")

        diags = [
            d
            for d in DiagnosticEngine(select={"BSL273"}).check_file(str(fixture))
            if d.code == "BSL273"
        ]

        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (6, 8, 6, 43),
            (49, 8, 49, 42),
            (59, 8, 59, 44),
            (79, 8, 79, 51),
        ]
        assert {d.severity for d in diags} == {Severity.ERROR}
        assert {d.message for d in diags} == {
            "Не следует использовать виртуальные таблицы без параметров"
        }


# BSL277 — TestBsl277WrongUseOfRollbackTransaction
class TestBsl277WrongUseOfRollbackTransaction:
    def test_rollback_outside_except_reports_exact_call(self, tmp_path: Path) -> None:
        content = "Процедура Тест()\n    ОтменитьТранзакцию();\nКонецПроцедуры\n"

        diags = [d for d in _check(content, tmp_path, select={"BSL277"}) if d.code == "BSL277"]

        assert [
            (d.line, d.character, d.end_line, d.end_character, d.severity, d.message) for d in diags
        ] == [(2, 4, 2, 22, Severity.ERROR, _rule_msg("BSL277"))]

    def test_rollback_first_in_except_is_clean(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Попытка
                    Выполнить();
                Исключение
                    ОтменитьТранзакцию();
                    ВызватьИсключение;
                КонецПопытки;
            КонецПроцедуры
        """

        assert "BSL277" not in _codes(_check(content, tmp_path, select={"BSL277"}))

    @pytest.mark.external_bslls
    def test_matches_bslls_fixture(self) -> None:
        fixture = (
            Path(".tmp/external-fixtures/bsl-language-server/src/test/resources/diagnostics")
            / "WrongUseOfRollbackTransactionMethodDiagnostic.bsl"
        )
        if not fixture.exists():
            pytest.skip("BSLLS fixture is not available")

        diags = [
            d
            for d in DiagnosticEngine(select={"BSL277"}).check_file(str(fixture))
            if d.code == "BSL277"
        ]

        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (8, 8, 8, 26),
            (12, 4, 12, 22),
            (30, 4, 30, 23),
        ]
        assert {d.severity for d in diags} == {Severity.ERROR}
        assert {d.message for d in diags} == {
            "Метод ОтменитьТранзакцию() должен быть в попытке и первым методом блока исключения"
        }


# BSL276 — TestBsl276WrongUseFunctionProceedWithCall
class TestBsl276WrongUseFunctionProceedWithCall:
    def test_proceed_without_around_reports_exact_call(self, tmp_path: Path) -> None:
        content = "Процедура Тест()\n    ПродолжитьВызов();\nКонецПроцедуры\n"

        diags = [d for d in _check(content, tmp_path, select={"BSL276"}) if d.code == "BSL276"]

        assert [
            (d.line, d.character, d.end_line, d.end_character, d.severity, d.message) for d in diags
        ] == [(2, 4, 2, 19, Severity.ERROR, _rule_msg("BSL276"))]

    def test_proceed_in_around_method_is_clean(self, tmp_path: Path) -> None:
        content = '&Вместо("Тест")\nПроцедура Тест()\n    ПродолжитьВызов();\nКонецПроцедуры\n'

        assert "BSL276" not in _codes(_check(content, tmp_path, select={"BSL276"}))

    @pytest.mark.external_bslls
    def test_matches_bslls_fixture(self) -> None:
        fixture = (
            Path(".tmp/external-fixtures/bsl-language-server/src/test/resources/diagnostics")
            / "WrongUseFunctionProceedWithCallDiagnostic.bsl"
        )
        if not fixture.exists():
            pytest.skip("BSLLS fixture is not available")

        diags = [
            d
            for d in DiagnosticEngine(select={"BSL276"}).check_file(str(fixture))
            if d.code == "BSL276"
        ]

        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (2, 4, 2, 19),
            (6, 4, 6, 19),
            (11, 13, 11, 28),
            (17, 13, 17, 28),
        ]
        assert {d.severity for d in diags} == {Severity.ERROR}
        assert {d.message for d in diags} == {
            "Использовать функцию ПродолжитьВызов() можно только в расширениях "
            "и только в методах с аннотацией &Вместо."
        }


# BSL263 — TestBsl263UseLessForEach
class TestBsl263UseLessForEach:
    def test_reports_unused_iterator_in_for_each(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Для каждого Элемент Из Коллекция Цикл
                    ВыполнитьДействие(Коллекция);
                КонецЦикла;
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL263"}) if d.code == "BSL263"]

        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (2, 16, 2, 23)
        ]

    def test_skips_used_iterator_in_for_each(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Для каждого Элемент Из Коллекция Цикл
                    ВыполнитьДействие(Элемент);
                КонецЦикла;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL263"})

        assert "BSL263" not in _codes(diags)

    def test_skips_module_variable_iterator_name(self, tmp_path: Path) -> None:
        content = """\
            Перем Элемент;

            Процедура Тест()
                Для каждого Элемент Из Коллекция Цикл
                    ВыполнитьДействие(Коллекция);
                КонецЦикла;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL263"})

        assert "BSL263" not in _codes(diags)

    @pytest.mark.external_bslls
    def test_matches_bslls_fixture(self) -> None:
        fixture = (
            Path(".tmp/external-fixtures/bsl-language-server/src/test/resources/diagnostics")
            / "UseLessForEachDiagnostic.bsl"
        )
        if not fixture.exists():
            pytest.skip("BSLLS fixture is not available")

        diags = [
            d
            for d in DiagnosticEngine(select={"BSL263"}).check_file(str(fixture))
            if d.code == "BSL263"
        ]

        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (3, 12, 3, 20),
            (40, 16, 40, 26),
        ]
        assert {d.severity for d in diags} == {Severity.ERROR}
        assert {d.message for d in diags} == {"Итератор не используется в теле цикла"}


# BSL199 — TestBsl199IfElseIfEndsWithElse
class TestBsl199IfElseIfEndsWithElse:
    def test_reports_elseif_chain_without_else_from_cst(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Если А Тогда
                    Б = 1;
                ИначеЕсли В Тогда
                    Б = 2;
                КонецЕсли;
            КонецПроцедуры
        """
        path = tmp_path / "test.bsl"
        path.write_text(textwrap.dedent(content), encoding="utf-8")

        diags = [
            d
            for d in DiagnosticEngine(select={"BSL199"}).check_file(str(path))
            if d.code == "BSL199"
        ]

        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (6, 4, 6, 13)
        ]

    def test_elseif_chain_with_else_is_clean(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Если А Тогда
                    Б = 1;
                ИначеЕсли В Тогда
                    Б = 2;
                Иначе
                    Б = 3;
                КонецЕсли;
            КонецПроцедуры
        """
        path = tmp_path / "test.bsl"
        path.write_text(textwrap.dedent(content), encoding="utf-8")

        diags = DiagnosticEngine(select={"BSL199"}).check_file(str(path))
        assert "BSL199" not in _codes(diags)

    @pytest.mark.external_bslls
    def test_matches_bslls_fixture(self) -> None:
        fixture = (
            Path(".tmp/external-fixtures/bsl-language-server/src/test/resources/diagnostics")
            / "IfElseIfEndsWithElseDiagnostic.bsl"
        )
        if not fixture.exists():
            pytest.skip("BSLLS fixture is not available")

        diags = [
            d
            for d in DiagnosticEngine(select={"BSL199"}).check_file(str(fixture))
            if d.code == "BSL199"
        ]

        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (21, 0, 21, 9),
        ]
        assert {d.severity for d in diags} == {Severity.WARNING}
        assert {d.message for d in diags} == {
            'Синтаксическая конструкция вида "Если...Тогда...ИначеЕсли..." '
            'должна содержать ветвь "Иначе".'
        }


# BSL198 — TestBsl198IfElseDuplicatedCondition
class TestBsl198IfElseDuplicatedCondition:
    def test_reports_duplicate_elseif_condition_from_cst(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Если П = 0 Тогда
                    Возврат;
                ИначеЕсли П = 1 Тогда
                    Возврат;
                ИначеЕсли П = 1 Тогда
                    Возврат;
                КонецЕсли;
            КонецПроцедуры
        """
        path = tmp_path / "test.bsl"
        path.write_text(textwrap.dedent(content), encoding="utf-8")

        diags = [
            d
            for d in DiagnosticEngine(select={"BSL198"}).check_file(str(path))
            if d.code == "BSL198"
        ]

        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (4, 14, 4, 19)
        ]
        assert {d.severity for d in diags} == {Severity.WARNING}

    @pytest.mark.external_bslls
    def test_matches_bslls_fixture(self) -> None:
        fixture = (
            Path(".tmp/external-fixtures/bsl-language-server/src/test/resources/diagnostics")
            / "IfElseDuplicatedConditionDiagnostic.bsl"
        )
        if not fixture.exists():
            pytest.skip("BSLLS fixture is not available")

        diags = [
            d
            for d in DiagnosticEngine(select={"BSL198"}).check_file(str(fixture))
            if d.code == "BSL198"
        ]

        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (4, 10, 4, 15),
            (18, 10, 18, 15),
            (21, 13, 21, 18),
            (42, 5, 42, 17),
        ]
        assert {d.severity for d in diags} == {Severity.WARNING}
        assert {d.message for d in diags} == {
            'Синтаксическая конструкция "Если...Тогда...ИначеЕсли..." '
            "содержит повторяющиеся условия"
        }


# BSL197 — TestBsl197IfElseDuplicatedCodeBlock
class TestBsl197IfElseDuplicatedCodeBlock:
    def test_duplicate_else_block_reports_exact_statement(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест(Флаг)
                Если Флаг Тогда
                    Значение = 1;
                Иначе
                    Значение = 1;
                КонецЕсли;
            КонецПроцедуры
        """

        diags = [d for d in _check(content, tmp_path, select={"BSL197"}) if d.code == "BSL197"]

        assert [
            (d.line, d.character, d.end_line, d.end_character, d.severity, d.message) for d in diags
        ] == [(3, 8, 3, 21, Severity.INFORMATION, _rule_msg("BSL197"))]

    def test_distinct_if_else_blocks_are_clean(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест(Флаг)
                Если Флаг Тогда
                    Значение = 1;
                Иначе
                    Значение = 2;
                КонецЕсли;
            КонецПроцедуры
        """

        assert "BSL197" not in _codes(_check(content, tmp_path, select={"BSL197"}))

    @pytest.mark.external_bslls
    def test_matches_bslls_fixture(self) -> None:
        fixture = (
            Path(".tmp/external-fixtures/bsl-language-server/src/test/resources/diagnostics")
            / "IfElseDuplicatedCodeBlockDiagnostic.bsl"
        )
        if not fixture.exists():
            pytest.skip("BSLLS fixture is not available")

        diags = [
            d
            for d in DiagnosticEngine(select={"BSL197"}).check_file(str(fixture))
            if d.code == "BSL197"
        ]

        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (10, 1, 11, 9),
            (27, 1, 28, 9),
            (40, 1, 48, 11),
            (41, 2, 42, 10),
            (54, 2, 55, 10),
        ]
        assert {d.severity for d in diags} == {Severity.INFORMATION}
        assert {d.message for d in diags} == {
            'Синтаксическая конструкция "Если...Тогда...ИначеЕсли..." '
            "содержит повторяющиеся блоки кода"
        }


# BSL225 — TestBsl225NumberOfValuesInStructureConstructorBslls
class TestBsl225NumberOfValuesInStructureConstructorBslls:
    @pytest.mark.external_bslls
    def test_matches_bslls_fixture(self) -> None:
        fixture = (
            Path(".tmp/external-fixtures/bsl-language-server/src/test/resources/diagnostics")
            / "NumberOfValuesInStructureConstructorDiagnostic.bsl"
        )
        if not fixture.exists():
            pytest.skip("BSLLS fixture is not available")

        diags = [
            d
            for d in DiagnosticEngine(select={"BSL225"}).check_file(str(fixture))
            if d.code == "BSL225"
        ]

        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (19, 12, 19, 119),
            (24, 28, 24, 89),
            (66, 9, 66, 78),
            (71, 28, 71, 88),
        ]
        assert {d.severity for d in diags} == {Severity.INFORMATION}
        assert {d.message for d in diags} == {
            "Уменьшите количество значений свойств, передаваемых в конструктор структуры"
        }


# BSL262 — TestBsl262UsageWriteLogEvent
class TestBsl262UsageWriteLogEvent:
    def test_error_info_assigned_before_detailed_presentation_is_clean(
        self, tmp_path: Path
    ) -> None:
        content = """\
            Попытка
            Исключение
                Отказ = Истина;
                Ошибка = ИнформацияОбОшибке();
                ЗаписьЖурналаРегистрации("Событие", УровеньЖурналаРегистрации.Ошибка, , , ПодробноеПредставлениеОшибки(Ошибка));
            КонецПопытки;
        """

        diags = _check(content, tmp_path, select={"BSL262"})

        assert "BSL262" not in _codes(diags)

    def test_variable_comment_expression_is_clean(self, tmp_path: Path) -> None:
        content = """\
            Попытка
            Исключение
                Ошибка = ИнформацияОбОшибке();
                Комментарий = СтрШаблон("Ошибка: %1", КраткоеПредставлениеОшибки(Ошибка));
                ЗаписьЖурналаРегистрации("Событие", УровеньЖурналаРегистрации.Ошибка, , , Комментарий);
            КонецПопытки;
        """

        diags = _check(content, tmp_path, select={"BSL262"})

        assert "BSL262" not in _codes(diags)

    def test_direct_brief_error_description_reports(self, tmp_path: Path) -> None:
        content = """\
            Попытка
            Исключение
                Ошибка = ИнформацияОбОшибке();
                ЗаписьЖурналаРегистрации("Событие", УровеньЖурналаРегистрации.Ошибка, , , КраткоеПредставлениеОшибки(Ошибка));
            КонецПопытки;
        """

        diags = _check(content, tmp_path, select={"BSL262"})

        assert "BSL262" in _codes(diags)

    @pytest.mark.external_bslls
    def test_matches_bslls_fixture(self) -> None:
        fixture = (
            Path(".tmp/external-fixtures/bsl-language-server/src/test/resources/diagnostics")
            / "UsageWriteLogEventDiagnostic.bsl"
        )
        if not fixture.exists():
            pytest.skip("BSLLS fixture is not available")

        diags = [
            diag
            for diag in DiagnosticEngine(select={"BSL262"}).check_file(str(fixture))
            if diag.code == "BSL262"
        ]

        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (4, 4, 4, 39),
            (5, 4, 5, 73),
            (6, 4, 6, 77),
            (8, 4, 10, 61),
            (12, 4, 12, 79),
            (17, 6, 18, 25),
            (24, 6, 25, 24),
            (32, 6, 33, 45),
            (39, 6, 40, 37),
            (46, 6, 47, 21),
            (191, 6, 193, 56),
            (205, 6, 207, 22),
            (220, 6, 222, 22),
            (287, 12, 292, 39),
            (355, 6, 357, 73),
            (369, 6, 371, 22),
            (384, 6, 386, 22),
            (440, 12, 445, 39),
        ]
        assert {diag.severity for diag in diags} == {Severity.INFORMATION}
        assert {diag.message for diag in diags} == {
            "Неверное число параметров метода",
            'Не указан 2й параметр с типом "УровеньЖурналаРегистрации"',
            'Не указан 5й параметр "Комментарий"',
            'Нужно указывать уровень "Ошибка" при записи в журнал регистрации внутри блока Исключение-КонецПопытки',
            'В тексте комментария нет вызова "ПодробноеПредставлениеОшибки(ИнформацияОбОшибке())"',
        }


# BSL151 — TestBsl151BeginTransactionBeforeTryCatch
class TestBsl151BeginTransactionBeforeTryCatch:
    def test_same_line_statement_after_begin_transaction_is_reported(self, tmp_path: Path) -> None:
        content = """
Процедура Тест()
    НачатьТранзакцию(); Метод();
КонецПроцедуры
"""

        diags = _check(content, tmp_path, select={"BSL151"})

        bsl151 = [diag for diag in diags if diag.code == "BSL151"]
        assert [(d.line, d.character, d.end_line, d.end_character) for d in bsl151] == [
            (3, 4, 3, 23)
        ]

    @pytest.mark.external_bslls
    def test_matches_bslls_fixture(self) -> None:
        fixture = (
            Path(".tmp/external-fixtures/bsl-language-server/src/test/resources/diagnostics")
            / "BeginTransactionBeforeTryCatchDiagnostic.bsl"
        )
        if not fixture.exists():
            pytest.skip("BSLLS fixture is not available")

        diags = [
            diag
            for diag in DiagnosticEngine(select={"BSL151"}).check_file(str(fixture))
            if diag.code == "BSL151"
        ]

        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (30, 4, 30, 23),
            (43, 8, 43, 27),
            (56, 4, 56, 23),
            (69, 8, 69, 27),
            (78, 4, 78, 23),
            (91, 4, 91, 23),
            (103, 0, 103, 19),
        ]
        assert {diag.severity for diag in diags} == {Severity.ERROR}
        assert {diag.message for diag in diags} == {
            "Метод 'НачатьТранзакцию' должен быть за пределами блока "
            "'Попытка-Исключение' непосредственно перед оператором 'Попытка'"
        }


# BSL157 — TestBsl157CommitTransactionOutsideTryCatch
class TestBsl157CommitTransactionOutsideTryCatch:
    def test_commit_not_last_in_try_is_reported(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Попытка
                    ЗафиксироватьТранзакцию();
                    Сообщить("после фиксации");
                Исключение
                    ОтменитьТранзакцию();
                КонецПопытки;
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL157"}) if d.code == "BSL157"]
        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (3, 8, 3, 34)
        ]

    def test_commit_last_before_except_is_valid(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Попытка
                    Действие();
                    ЗафиксироватьТранзакцию();
                Исключение
                    ОтменитьТранзакцию();
                КонецПопытки;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL157"})
        assert "BSL157" not in _codes(diags)

    @pytest.mark.external_bslls
    def test_matches_bslls_fixture(self) -> None:
        fixture = (
            Path(".tmp/external-fixtures/bsl-language-server/src/test/resources/diagnostics")
            / "CommitTransactionOutsideTryCatchDiagnostic.bsl"
        )
        if not fixture.exists():
            pytest.skip("BSLLS fixture is not available")

        diags = [
            diag
            for diag in DiagnosticEngine(select={"BSL157"}).check_file(str(fixture))
            if diag.code == "BSL157"
        ]

        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (37, 4, 37, 30),
            (46, 12, 46, 38),
            (58, 8, 58, 34),
            (67, 4, 67, 30),
            (75, 8, 75, 34),
            (87, 8, 87, 34),
            (99, 8, 99, 34),
            (107, 0, 107, 26),
        ]
        assert {diag.severity for diag in diags} == {Severity.ERROR}
        assert {diag.message for diag in diags} == {
            "Метод 'ЗафиксироватьТранзакцию' должен идти последним в блоке "
            "'Попытка' перед оператором 'Исключение'"
        }

    @pytest.mark.external_bslls
    def test_matches_bslls_single_sub_fixture(self) -> None:
        fixture = (
            Path(".tmp/external-fixtures/bsl-language-server/src/test/resources/diagnostics")
            / "CommitTransactionOutsideTryCatchDiagnosticSingleSub.bsl"
        )
        if not fixture.exists():
            pytest.skip("BSLLS fixture is not available")

        diags = [
            diag
            for diag in DiagnosticEngine(select={"BSL157"}).check_file(str(fixture))
            if diag.code == "BSL157"
        ]

        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (4, 4, 4, 30)
        ]
        assert {diag.severity for diag in diags} == {Severity.ERROR}


# BSL230 — TestBsl230PairingBrokenTransaction
class TestBsl230PairingBrokenTransaction:
    def test_tab_indented_rollback_range_includes_call_parentheses(self, tmp_path: Path) -> None:
        content = "Процедура Тест()\n\t\tОтменитьТранзакцию();\nКонецПроцедуры\n"
        path = tmp_path / "RollbackTabs.bsl"
        path.write_text(content, encoding="utf-8")

        diags = [
            diag
            for diag in DiagnosticEngine(select={"BSL230"}).check_file(str(path))
            if diag.code == "BSL230"
        ]

        assert len(diags) == 1
        assert (diags[0].line, diags[0].character, diags[0].end_character) == (2, 2, 22)

    @pytest.mark.external_bslls
    def test_matches_bslls_fixture(self) -> None:
        fixture = (
            Path(".tmp/external-fixtures/bsl-language-server/src/test/resources/diagnostics")
            / "PairingBrokenTransactionDiagnostic.bsl"
        )
        if not fixture.exists():
            pytest.skip("BSLLS sources are not available")

        diags = [
            diag
            for diag in DiagnosticEngine(select={"BSL230"}).check_file(str(fixture))
            if diag.code == "BSL230"
        ]

        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (28, 4, 28, 27),
            (32, 4, 32, 20),
            (32, 4, 32, 20),
            (41, 4, 41, 27),
            (45, 4, 45, 20),
            (45, 4, 45, 20),
            (46, 4, 46, 20),
            (53, 4, 53, 20),
            (54, 4, 54, 20),
            (57, 4, 57, 20),
            (84, 4, 84, 27),
            (88, 4, 88, 27),
            (89, 4, 89, 22),
            (93, 4, 93, 20),
            (94, 8, 94, 24),
            (96, 8, 96, 24),
            (102, 4, 102, 27),
            (106, 4, 106, 20),
            (107, 8, 107, 24),
            (109, 8, 109, 24),
            (114, 4, 114, 27),
        ]
        assert {diag.severity for diag in diags} == {Severity.ERROR}
        assert any("CommitTransaction" in diag.message for diag in diags)
        assert any("RollbackTransaction" in diag.message for diag in diags)
        assert any("ЗафиксироватьТранзакцию" in diag.message for diag in diags)
        assert any("ОтменитьТранзакцию" in diag.message for diag in diags)


# BSL268 — TestBsl268UsingFindElementByString
class TestBsl268UsingFindElementByString:
    def test_string_argument_range_covers_whole_call(self, tmp_path: Path) -> None:
        content = (
            'Процедура Тест()\n    Код = Справочники.Коды.НайтиПоКоду("1010836");\nКонецПроцедуры\n'
        )
        path = tmp_path / "FindByCode.bsl"
        path.write_text(content, encoding="utf-8")

        diags = [
            diag
            for diag in DiagnosticEngine(select={"BSL268"}).check_file(str(path))
            if diag.code == "BSL268"
        ]

        assert len(diags) == 1
        line = content.splitlines()[1]
        assert diags[0].character == line.index("НайтиПоКоду")
        assert diags[0].end_character == line.index(")") + 1


# registry/meta — TestRuleMetadataCompleteness
class TestRuleMetadataCompleteness:
    def test_all_rules_in_metadata(self) -> None:
        from onec_hbk_bsl.analysis.diagnostics import _BSLLS_NAME_TO_CODE, RULE_METADATA

        missing = set(_BSLLS_NAME_TO_CODE.values()) - set(RULE_METADATA.keys())
        assert not missing, f"Missing BSLLS RULE_METADATA entries: {missing}"
