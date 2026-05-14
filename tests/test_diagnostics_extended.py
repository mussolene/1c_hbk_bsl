"""
Extended tests for DiagnosticEngine — covers rules BSL003–BSL017.

Each test class covers one rule, with:
  - A positive case (issue detected)
  - A negative case (no false positive)
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from onec_hbk_bsl.analysis.diagnostics import (
    Diagnostic,
    DiagnosticEngine,
    Severity,
    path_is_likely_form_module_bsl,
)
from onec_hbk_bsl.indexer.incremental import IncrementalIndexer
from onec_hbk_bsl.indexer.symbol_index import SymbolIndex

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
# BSL172 — DataExchangeLoading
# ---------------------------------------------------------------------------


class TestBsl172DataExchangeLoadingParity:
    def test_requires_exchange_check_with_return(self, tmp_path: Path) -> None:
        content = """\
            Процедура ПередЗаписью(Отказ, Замещение)
                Если Отказ Тогда
                    Возврат;
                КонецЕсли;
            КонецПроцедуры
        """
        path = tmp_path / "Catalogs" / "Тест" / "Ext" / "RecordSetModule.bsl"
        path.parent.mkdir(parents=True)
        path.write_text(textwrap.dedent(content), encoding="utf-8")
        diags = DiagnosticEngine(select={"BSL172"}).check_file(str(path))
        assert "BSL172" in _codes(diags)

    def test_exchange_check_in_if_branch_satisfies_rule(self, tmp_path: Path) -> None:
        content = """\
            Процедура ПередЗаписью(Отказ, Замещение)
                Если ОбменДанными.Загрузка Тогда
                    Возврат;
                КонецЕсли;
            КонецПроцедуры
        """
        path = tmp_path / "Catalogs" / "Тест" / "Ext" / "RecordSetModule.bsl"
        path.parent.mkdir(parents=True)
        path.write_text(textwrap.dedent(content), encoding="utf-8")
        diags = DiagnosticEngine(select={"BSL172"}).check_file(str(path))
        assert "BSL172" not in _codes(diags)

    def test_non_supported_module_type_is_skipped(self, tmp_path: Path) -> None:
        content = """\
            Процедура ПередЗаписью(Отказ, СтандартнаяОбработка)
                Если Отказ Тогда
                    Возврат;
                КонецЕсли;
            КонецПроцедуры
        """
        path = tmp_path / "Forms" / "ФормаСписка" / "Ext" / "Form" / "Module.bsl"
        path.parent.mkdir(parents=True)
        path.write_text(textwrap.dedent(content), encoding="utf-8")
        diags = DiagnosticEngine(select={"BSL172"}).check_file(str(path))
        assert "BSL172" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL215 — MissingParameterDescription
# ---------------------------------------------------------------------------


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

    def test_missing_single_param_message_matches_bslls_style(self, tmp_path: Path) -> None:
        content = """\
            // Описание метода.
            // Параметры:
            //   Имя - описание
            Функция Обработать(Имя, Стр)
            КонецФункции
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL215"}) if d.code == "BSL215"]
        assert any(d.message == 'Необходимо добавить описание параметра "Стр"' for d in diags)

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
        assert diags[0].message == "Необходимо исправить порядок описаний параметров"


# ---------------------------------------------------------------------------
# BSL237 — RedundantAccessToObject
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# BSL175 / BSL176 / BSL177 / BSL179 / BSL195 — deprecated API parity
# ---------------------------------------------------------------------------


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
        assert any("ОтображатьШкалу" in d.message for d in bsl175)
        assert any("ОчиститьЖурналРегистрации" in d.message for d in bsl175)

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
        assert "СтарыйМетод" in bsl176[0].message

    def test_bsl177_deprecated_client_app_method(self, tmp_path: Path) -> None:
        content = """\
            Процедура Test()
                test = GetShortApplicationCaption();
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL177"})
        bsl177 = [d for d in diags if d.code == "BSL177"]
        assert len(bsl177) == 1
        assert "ClientApplication.GetShortCaption" in bsl177[0].message

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
        assert bsl195[0].message == "Не рекомендуемое использование метода ПолучитьФорму"


# ---------------------------------------------------------------------------
# BSL180 / BSL184 / BSL185 / BSL188 / BSL203 / BSL226 / BSL247 / BSL250 /
# ---------------------------------------------------------------------------


class TestSecurityApiParityBatch:
    def test_bsl180_disable_safe_mode(self, tmp_path: Path) -> None:
        content = """\
            Процедура Метод()
                УстановитьБезопасныйРежим(Ложь);
                УстановитьБезопасныйРежим(Истина);
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL180"})
        assert _codes(diags) == ["BSL180"]

    def test_bsl183_execute_external_code_matches_bslls_fixture(self, tmp_path: Path) -> None:
        content = """
            &НаКлиенте
            Процедура ВыполнитьПроизвольныйКодНаКлиенте(Строка)
                Выполнить(Строка);
            КонецПроцедуры

            &НаСервере
            Процедура ВыполнитьПроизвольныйКодНаСервере(Строка)
                Выполнить(Строка);
            КонецПроцедуры

            &НаСервереБезКонтекста
            Процедура ВыполнитьПроизвольныйКодНаСервереБезКонтекста(Строка)
                Выполнить(Строка);
            КонецПроцедуры

            &НаКлиентеНаСервереБезКонтекста
            Функция РассчитатьЧтоТоИзСтрокиБезКонтекст(Строка)
                Возврат Вычислить(Строка);
            КонецФункции

            &НаКлиентеНаСервере
            Функция РассчитатьЧтоТоИзСтроки(Строка)
                Возврат Вычислить(Строка);
            КонецФункции

            Функция БезОшибок(Строка)
                Возврат ВычислитьЧтоТо(Строка);
            КонецФункции

            Функция МетодБезДеректив(Строка)
                Возврат Вычислить(Строка);
            КонецФункции

            &НаКлиенте
            Функция ВычислениеНаКлиенте(Строка)
                Возврат Вычислить(Строка);
            КонецФункции
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL183"}) if d.code == "BSL183"]
        assert [
            (d.line, d.character, d.end_line, d.end_character, d.severity.name) for d in diags
        ] == [
            (9, 4, 9, 21, "ERROR"),
            (14, 4, 14, 21, "ERROR"),
            (19, 12, 19, 29, "ERROR"),
            (24, 12, 24, 29, "ERROR"),
            (32, 12, 32, 29, "ERROR"),
        ]
        assert {d.message for d in diags} == {"Запрещено выполнение произвольного кода на сервере"}

    def test_bsl184_execute_external_code_in_common_module(self, tmp_path: Path) -> None:
        content = """
            Процедура ВыполнитьПроизвольныйКод(Строка)
                Выполнить(Строка);
            КонецПроцедуры

            Функция РассчитатьЧтоТоИзСтроки(Строка)
                Возврат Вычислить(Строка);
            КонецФункции

            Функция БезОшибок(Строка)
                Возврат ВычислитьЧтоТо(Строка);
            КонецФункции
        """
        common_modules = tmp_path / "Config" / "CommonModules"
        common_modules.mkdir(parents=True)
        (common_modules / "Тест.xml").write_text(
            textwrap.dedent(
                """\
                <MetaDataObject>
                  <CommonModule>
                    <Properties>
                      <Name>Тест</Name>
                      <ClientManagedApplication>false</ClientManagedApplication>
                      <Server>true</Server>
                      <ExternalConnection>false</ExternalConnection>
                      <ClientOrdinaryApplication>false</ClientOrdinaryApplication>
                      <ServerCall>false</ServerCall>
                    </Properties>
                  </CommonModule>
                </MetaDataObject>
                """
            ),
            encoding="utf-8",
        )
        path = common_modules / "Тест" / "Ext" / "Module.bsl"
        path.parent.mkdir(parents=True)
        path.write_text(textwrap.dedent(content), encoding="utf-8")
        diags = [
            d
            for d in DiagnosticEngine(select={"BSL184"}).check_file(str(path))
            if d.code == "BSL184"
        ]
        assert [
            (d.line, d.character, d.end_line, d.end_character, d.severity.name) for d in diags
        ] == [
            (3, 4, 3, 21, "WARNING"),
            (7, 12, 7, 29, "WARNING"),
        ]

    def test_bsl184_skips_non_server_common_module(self, tmp_path: Path) -> None:
        common_modules = tmp_path / "Config" / "CommonModules"
        common_modules.mkdir(parents=True)
        (common_modules / "Тест.xml").write_text(
            textwrap.dedent(
                """\
                <MetaDataObject>
                  <CommonModule>
                    <Properties>
                      <Name>Тест</Name>
                      <ClientManagedApplication>true</ClientManagedApplication>
                      <Server>false</Server>
                      <ExternalConnection>false</ExternalConnection>
                      <ClientOrdinaryApplication>false</ClientOrdinaryApplication>
                      <ServerCall>false</ServerCall>
                    </Properties>
                  </CommonModule>
                </MetaDataObject>
                """
            ),
            encoding="utf-8",
        )
        path = common_modules / "Тест" / "Ext" / "Module.bsl"
        path.parent.mkdir(parents=True)
        path.write_text("Процедура П()\n    Выполнить(Строка);\nКонецПроцедуры\n", encoding="utf-8")
        diags = DiagnosticEngine(select={"BSL184"}).check_file(str(path))
        assert "BSL184" not in _codes(diags)

    def test_bsl226_os_users_method_matches_bslls_fixture(self, tmp_path: Path) -> None:
        content = """\
            Функция Тест1()
            Сообщить("Здесь не должно сработать");
            КонецФункции

            Функция Тест2()
            Пользователи = ПользователиОС(); // сработает здесь
            КонецФункции

            Функция Тест3()
            Users = OSUsers(); // сработает здесь
            КонецФункции

            Функция Тест4()
            Users = osUsers(); // сработает здесь
            КонецФункции
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL226"}) if d.code == "BSL226"]
        assert [
            (d.line, d.character, d.end_line, d.end_character, d.severity.name) for d in diags
        ] == [
            (6, 15, 6, 29, "WARNING"),
            (10, 8, 10, 15, "WARNING"),
            (14, 8, 14, 15, "WARNING"),
        ]
        assert {d.message for d in diags} == {
            "Проверить потенциально вредоносное использование метода ПользователиОС"
        }

    def test_bsl247_set_privileged_mode_matches_bslls_fixture(self, tmp_path: Path) -> None:
        content = """\
            &НаСервере
            Процедура Метод()
                УстановитьПривилегированныйРежим(Истина); // есть замечание
                Значение = Истина;
                УстановитьПривилегированныйРежим(Значение); // есть замечание

                УстановитьПривилегированныйРежим(Ложь); // нет замечания
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL247"}) if d.code == "BSL247"]
        assert [
            (d.line, d.character, d.end_line, d.end_character, d.severity.name) for d in diags
        ] == [
            (3, 4, 3, 36, "WARNING"),
            (5, 4, 5, 36, "WARNING"),
        ]
        assert {d.message for d in diags} == {"Проверьте установку привилегированного режима"}

    def test_bsl250_temp_files_dir_matches_bslls_fixture(self, tmp_path: Path) -> None:
        content = """\
            Функция Тест()
                Каталог = КаталогВременныхФайлов();  // Срабатывание здесь
                ИмяФайла = Строка(Новый УникальныйИдентификатор) + ".xml";
                ИмяПромежуточногоФайла = Каталог + ИмяФайла;
                Данные.Записать(ИмяПромежуточногоФайла);
            КонецФункции

            Function Test()
                Catalog = TempFilesDir(); // Срабатывание здесь
                FileName = Str(New UUID);
            EndFunction
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL250"}) if d.code == "BSL250"]
        assert [
            (d.line, d.character, d.end_line, d.end_character, d.severity.name) for d in diags
        ] == [
            (2, 14, 2, 36, "WARNING"),
            (9, 14, 9, 26, "WARNING"),
        ]
        assert {d.message for d in diags} == {
            "Не рекомендуемый вызов функции КаталогВременныхФайлов()"
        }

    def test_bsl267_external_code_tools_matches_bslls_fixture(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                ИмяОбработки = ВнешниеОбработки.Подключить("ПутьКОбработке", ЛОЖЬ); // <-- Ошибка
                Обработка = ВнешниеОбработки.Создать(ИмяОбработки); // <-- Ошибка

                ИмяОтчета = ExternalReports.Connect("Path", true); // <-- Ошибка
                Отчет = ExternalReports.Create(ИмяОтчета); // <-- Ошибка

                Расширение = РасширенияКонфигурации.Создать("ИмяРасширения"); // <-- Ошибка
                СписокРасширений = Новый СписокЗначений;
                СписокРасширений.Добавить(РасширенияКонфигурации.Создать("ИмяРасширения2")); // <-- Ошибка
            КонецПроцедуры

            Процедура Тест2()
                Справочники.ВнешниеОбработки.Подключить("ПутьКОбработке", ЛОЖЬ); // <-- Не ошибка
                Обработка.ExternalReports.Connect("Path", true); // <-- не ошибка
                ExternalReports.Connect("Path", true).Create("name"); // <-- Ошибка
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL267"}) if d.code == "BSL267"]
        assert [
            (d.line, d.character, d.end_line, d.end_character, d.severity.name) for d in diags
        ] == [
            (2, 19, 2, 70, "ERROR"),
            (3, 16, 3, 54, "ERROR"),
            (5, 16, 5, 53, "ERROR"),
            (6, 12, 6, 45, "ERROR"),
            (8, 17, 8, 64, "ERROR"),
            (10, 30, 10, 78, "ERROR"),
            (16, 4, 16, 56, "ERROR"),
        ]
        assert {d.message for d in diags} == {
            "Запрещено использование возможности выполнения внешнего кода"
        }

    def test_bsl272_synchronous_calls_matches_bslls_fixture(self, tmp_path: Path) -> None:
        fixture = (
            Path(__file__).resolve().parents[1]
            / ".agent/tmp/bslls-source/src/test/resources/diagnostics/UsingSynchronousCallsDiagnostic.bsl"
        )
        if not fixture.exists():
            pytest.skip("BSLLS upstream fixture is not available")
        content = fixture.read_text(encoding="utf-8")
        bsl_file = tmp_path / "UsingSynchronousCallsDiagnostic.bsl"
        bsl_file.write_text(content, encoding="utf-8")
        diags = [
            d
            for d in DiagnosticEngine(select={"BSL272"}).check_file(str(bsl_file))
            if d.code == "BSL272"
        ]
        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (3, 12, 4, 57),
            (22, 4, 22, 84),
            (30, 4, 30, 26),
            (44, 9, 44, 58),
            (73, 9, 73, 67),
            (104, 9, 104, 50),
            (123, 9, 123, 61),
            (139, 4, 139, 50),
            (149, 4, 149, 33),
            (160, 20, 160, 56),
            (173, 20, 173, 62),
            (185, 12, 185, 54),
            (186, 8, 186, 129),
            (199, 12, 199, 48),
            (200, 8, 200, 109),
            (215, 4, 215, 88),
            (226, 4, 226, 68),
            (237, 4, 237, 69),
            (248, 21, 248, 51),
            (261, 8, 261, 37),
            (275, 4, 275, 29),
            (286, 16, 286, 40),
            (297, 16, 297, 35),
            (308, 16, 308, 50),
            (319, 16, 319, 89),
            (345, 16, 345, 64),
            (369, 12, 369, 59),
            (392, 4, 392, 38),
        ]
        assert len(diags) == 28
        assert all(d.severity is Severity.WARNING for d in diags)
        assert any(
            d.message
            == "Вместо синхронного метода `Вопрос` необходимо использовать `ПоказатьВопрос`"
            for d in diags
        )
        assert any(
            d.message
            == "Вместо синхронного метода `ЗапуститьПриложение` необходимо использовать `НачатьЗапускПриложения`"
            for d in diags
        )

    def test_bsl272_skips_server_object_module(self, tmp_path: Path) -> None:
        path = tmp_path / "Catalogs" / "Тест" / "Ext" / "ObjectModule.bsl"
        path.parent.mkdir(parents=True)
        path.write_text(
            'Процедура П()\n    ЗапуститьПриложение("Таблица.xls");\nКонецПроцедуры\n',
            encoding="utf-8",
        )
        diags = DiagnosticEngine(select={"BSL272"}).check_file(str(path))
        assert "BSL272" not in _codes(diags)

    def test_bsl272_skips_staged_object_module_name(self, tmp_path: Path) -> None:
        path = tmp_path / "f000_ObjectModule.bsl"
        path.write_text(
            'Процедура П()\n    УдалитьФайлы("tmp.xml");\nКонецПроцедуры\n',
            encoding="utf-8",
        )
        diags = DiagnosticEngine(select={"BSL272"}).check_file(str(path))
        assert "BSL272" not in _codes(diags)

    def test_bsl185_external_app_starting(self, tmp_path: Path) -> None:
        content = """\
            Процедура Метод()
                ЗапуститьПриложение(СтрокаКоманды, ТекущийКаталог);
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL185"})
        assert "BSL185" in _codes(diags)


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
        assert any(diag.line == 1 and "HTTP-сервиса" in diag.message for diag in diags)

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
        assert "веб-сервиса" in diags[0].message


class TestTailParityBatches:
    def test_compilation_and_name_tail_pool(self, tmp_path: Path) -> None:
        form_path = tmp_path / "Catalogs" / "Тест" / "Forms" / "Форма" / "Ext" / "Module.bsl"
        form_path.parent.mkdir(parents=True)
        form_path.write_text(
            textwrap.dedent(
                """\
                Процедура ПроверитьБит()
                КонецПроцедуры

                Процедура Обработчик()
                    АвтоТестПроверка();
                    АвтоТестПроверка();
                    Коллекция.Добавить(Значение);
                    Коллекция.Добавить(Значение);
                    Найденный = Каталог.НайтиПоКоду("001");
                КонецПроцедуры
                """
            ),
            encoding="utf-8",
        )
        diags = DiagnosticEngine(select={"BSL169", "BSL181", "BSL182", "BSL196"}).check_file(
            str(form_path)
        )
        got = set(_codes(diags))
        assert {"BSL169", "BSL181", "BSL182", "BSL196"} <= got

    def test_needless_compilation_directive_in_manager_module(self, tmp_path: Path) -> None:
        path = tmp_path / "Catalogs" / "Тест" / "Ext" / "ManagerModule.bsl"
        path.parent.mkdir(parents=True)
        path.write_text(
            textwrap.dedent(
                """\
                &НаКлиенте
                Процедура Метод()
                КонецПроцедуры
                """
            ),
            encoding="utf-8",
        )
        diags = DiagnosticEngine(select={"BSL170"}).check_file(str(path))
        assert "BSL170" in _codes(diags)

    def test_unsafe_find_by_code_tail_rule(self, tmp_path: Path) -> None:
        path = tmp_path / "Catalogs" / "Тест" / "Ext" / "ManagerModule.bsl"
        path.parent.mkdir(parents=True)
        path.write_text(
            textwrap.dedent(
                """\
                Процедура Метод()
                    Найденный = Каталог.НайтиПоКоду("001");
                КонецПроцедуры
                """
            ),
            encoding="utf-8",
        )
        diags = DiagnosticEngine(select={"BSL260"}).check_file(str(path))
        assert "BSL260" in _codes(diags)

    def test_metadata_tail_pool(self, tmp_path: Path) -> None:
        root = tmp_path / "Config"
        root.mkdir(parents=True)
        (root / "Configuration.xml").write_text("<Configuration/>", encoding="utf-8")
        (root / "Roles").mkdir(parents=True)
        (root / "Roles" / "Менеджер.xml").write_text(
            "<Role><SetForNewObjects>true</SetForNewObjects></Role>",
            encoding="utf-8",
        )
        obj_dir = root / "InformationRegisters" / ("X" * 81)
        (obj_dir / "Forms" / "Форма" / "Ext").mkdir(parents=True)
        (root / "InformationRegisters" / f"{'X' * 81}.xml").write_text(
            textwrap.dedent(
                f"""\
                <MetaDataObject>
                    <InformationRegister>
                        <Properties><Name>{"X" * 81}</Name></Properties>
                        <ChildObjects>
                            <Attribute><Properties><Name>{"X" * 81}</Name></Properties></Attribute>
                            <Dimension>
                                <Properties>
                                    <Name>Измерение</Name>
                                    <DenyIncompleteValues>false</DenyIncompleteValues>
                                </Properties>
                            </Dimension>
                        </ChildObjects>
                    </InformationRegister>
                </MetaDataObject>
                """
            ),
            encoding="utf-8",
        )
        (obj_dir / "Forms" / "Форма" / "Ext" / "Form.xml").write_text(
            "<Form><Items><Item><DataPath>~ПлохойПуть</DataPath></Item></Items></Form>",
            encoding="utf-8",
        )
        module_path = obj_dir / "Forms" / "Форма" / "Ext" / "Module.bsl"
        module_path.write_text(
            textwrap.dedent(
                """\
                Процедура Метод()
                КонецПроцедуры
                """
            ),
            encoding="utf-8",
        )
        app_module = root / "Ext" / "ManagedApplicationModule.bsl"
        app_module.parent.mkdir(parents=True)
        app_module.write_text(
            "Процедура ПриНачалеРаботыСистемы()\nКонецПроцедуры\n", encoding="utf-8"
        )
        diags_form = DiagnosticEngine(select={"BSL174", "BSL211", "BSL241", "BSL274"}).check_file(
            str(module_path)
        )
        assert {"BSL174", "BSL211", "BSL241", "BSL274"} <= set(_codes(diags_form))
        diags_app = DiagnosticEngine(select={"BSL246"}).check_file(str(app_module))
        assert "BSL246" in _codes(diags_app)

    def test_common_module_cross_reference_tail_pool(self, tmp_path: Path) -> None:
        root = tmp_path / "Config"
        root.mkdir(parents=True)
        (root / "Configuration.xml").write_text("<Configuration/>", encoding="utf-8")
        (root / "CommonModules" / "Обычный" / "Ext").mkdir(parents=True)
        (root / "CommonModules" / "Привилегированный" / "Ext").mkdir(parents=True)
        (root / "ScheduledJobs").mkdir(parents=True)
        (root / "EventSubscriptions").mkdir(parents=True)
        (root / "CommonModules" / "Обычный.xml").write_text(
            "<CommonModule><Name>Обычный</Name></CommonModule>", encoding="utf-8"
        )
        (root / "CommonModules" / "Привилегированный.xml").write_text(
            "<CommonModule><Name>Привилегированный</Name><Privileged>true</Privileged><Protected>true</Protected></CommonModule>",
            encoding="utf-8",
        )
        (root / "ScheduledJobs" / "Задание.xml").write_text(
            "<ScheduledJob><MethodName>CommonModule.Обычный.НетЭкспорта</MethodName></ScheduledJob>",
            encoding="utf-8",
        )
        (root / "EventSubscriptions" / "Подписка.xml").write_text(
            "<EventSubscription><Handler>Обычный.НеСуществующий</Handler></EventSubscription>",
            encoding="utf-8",
        )
        ordinary_module = root / "CommonModules" / "Обычный" / "Ext" / "Module.bsl"
        ordinary_module.write_text(
            textwrap.dedent(
                """\
                Процедура НетЭкспорта()
                    Привилегированный.Метод();
                    Обычный.Отсутствующий();
                КонецПроцедуры
                """
            ),
            encoding="utf-8",
        )
        (root / "CommonModules" / "Привилегированный" / "Ext" / "Module.bsl").write_text(
            "Процедура Метод() Экспорт\nКонецПроцедуры\n",
            encoding="utf-8",
        )
        session_module = root / "Ext" / "SessionModule.bsl"
        session_module.parent.mkdir(parents=True)
        session_module.write_text(
            "Процедура ПриНачалеРаботыСистемы()\nКонецПроцедуры\n", encoding="utf-8"
        )
        diags = DiagnosticEngine(select={"BSL213", "BSL214", "BSL231", "BSL242"}).check_file(
            str(ordinary_module)
        )
        assert {"BSL213", "BSL214", "BSL231", "BSL242"} <= set(_codes(diags))
        session_diags = DiagnosticEngine(select={"BSL232"}).check_file(str(session_module))
        assert "BSL232" in _codes(session_diags)

    def test_query_and_runtime_tail_pool(self, tmp_path: Path) -> None:
        path = tmp_path / "Catalogs" / "Тест" / "Forms" / "Форма" / "Ext" / "Module.bsl"
        path.parent.mkdir(parents=True)
        (tmp_path / "Configuration.xml").write_text("<Configuration/>", encoding="utf-8")
        (tmp_path / "Catalogs").mkdir(exist_ok=True)
        (tmp_path / "Catalogs" / "Тест.xml").write_text(
            "<MetaDataObject><Catalog><Properties><Name>Тест</Name></Properties></Catalog></MetaDataObject>",
            encoding="utf-8",
        )
        path.write_text(
            textwrap.dedent(
                """\
                &НаКлиенте
                Процедура ПриОткрытии()
                    СерверныйМетод();
                    Соединение = Новый HTTPСоединение("x", 80, "u", "p");
                    Если БезопасныйРежим() И Истина Тогда
                    КонецЕсли;
                    Запрос = Новый Запрос;
                    Запрос.Текст = "ВЫБРАТЬ
                    |  Левое.Тест КАК Поле,
                    |  Левое.Ссылка.Код КАК Код
                    |ИЗ НесуществующийСправочник КАК Основание
                    |    ЛЕВОЕ СОЕДИНЕНИЕ НесуществующийСправочник КАК Левое
                    |    ПО Истина";
                КонецПроцедуры

                &НаСервере
                Процедура СерверныйМетод()
                КонецПроцедуры
                """
            ),
            encoding="utf-8",
        )
        diags = DiagnosticEngine(
            select={"BSL187", "BSL236", "BSL238", "BSL244", "BSL261"}
        ).check_file(str(path))
        assert {"BSL187", "BSL236", "BSL238", "BSL244", "BSL261"} <= set(_codes(diags))

    def test_bsl238_skips_full_metadata_crawl(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = tmp_path / "Catalogs" / "Тест" / "Forms" / "Форма" / "Ext" / "Module.bsl"
        path.parent.mkdir(parents=True)
        (tmp_path / "Configuration.xml").write_text("<Configuration/>", encoding="utf-8")
        (tmp_path / "Catalogs").mkdir(exist_ok=True)
        (tmp_path / "Catalogs" / "Тест.xml").write_text(
            "<MetaDataObject><Catalog><Properties><Name>Тест</Name></Properties></Catalog></MetaDataObject>",
            encoding="utf-8",
        )
        path.write_text(
            textwrap.dedent(
                """\
                Процедура Тест()
                    Запрос = Новый Запрос;
                    Запрос.Текст = "ВЫБРАТЬ
                    |  Таблица.Ссылка.Код
                    |ИЗ Справочник.Тест КАК Таблица";
                КонецПроцедуры
                """
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "onec_hbk_bsl.analysis.diagnostics._crawl_config_cached",
            lambda *_args, **_kwargs: pytest.fail("full crawl is not expected for BSL238-only run"),
        )
        diags = DiagnosticEngine(select={"BSL238"}).check_file(str(path))
        assert "BSL238" in _codes(diags)

    def test_bsl246_uses_cached_role_index_without_full_crawl(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = tmp_path / "Config"
        root.mkdir(parents=True)
        (root / "Configuration.xml").write_text("<Configuration/>", encoding="utf-8")
        (root / "Roles").mkdir()
        (root / "Roles" / "ПлохаяРоль.xml").write_text(
            "<Role><SetForNewObjects>true</SetForNewObjects></Role>",
            encoding="utf-8",
        )
        app_module = root / "Ext" / "ManagedApplicationModule.bsl"
        app_module.parent.mkdir(parents=True)
        app_module.write_text(
            "Процедура ПриНачалеРаботыСистемы()\nКонецПроцедуры\n", encoding="utf-8"
        )
        monkeypatch.setattr(
            "onec_hbk_bsl.analysis.diagnostics._crawl_config_cached",
            lambda *_args, **_kwargs: pytest.fail("full crawl is not expected for BSL246-only run"),
        )
        monkeypatch.setattr(
            "onec_hbk_bsl.analysis.diagnostics._common_module_file_map",
            lambda *_args, **_kwargs: pytest.fail("module map is not expected for BSL246-only run"),
        )
        diags = DiagnosticEngine(select={"BSL246"}).check_file(str(app_module))
        assert "BSL246" in _codes(diags)

    def test_bsl231_skips_proc_name_index(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = tmp_path / "Config"
        root.mkdir(parents=True)
        (root / "Configuration.xml").write_text("<Configuration/>", encoding="utf-8")
        (root / "CommonModules" / "Обычный" / "Ext").mkdir(parents=True)
        (root / "CommonModules" / "Привилегированный" / "Ext").mkdir(parents=True)
        (root / "CommonModules" / "Обычный.xml").write_text(
            "<CommonModule><Name>Обычный</Name></CommonModule>", encoding="utf-8"
        )
        (root / "CommonModules" / "Привилегированный.xml").write_text(
            "<CommonModule><Name>Привилегированный</Name><Privileged>true</Privileged></CommonModule>",
            encoding="utf-8",
        )
        ordinary_module = root / "CommonModules" / "Обычный" / "Ext" / "Module.bsl"
        ordinary_module.write_text(
            "Процедура НетЭкспорта()\n    Привилегированный.Метод();\nКонецПроцедуры\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "onec_hbk_bsl.analysis.diagnostics._common_module_proc_names_map_cached",
            lambda *_args, **_kwargs: pytest.fail(
                "proc-name index is not expected for BSL231-only run"
            ),
        )
        diags = DiagnosticEngine(select={"BSL231"}).check_file(str(ordinary_module))
        assert "BSL231" in _codes(diags)

    def test_bsl213_skips_privileged_index(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = tmp_path / "Config"
        root.mkdir(parents=True)
        (root / "Configuration.xml").write_text("<Configuration/>", encoding="utf-8")
        (root / "CommonModules" / "Обычный" / "Ext").mkdir(parents=True)
        (root / "CommonModules" / "Привилегированный" / "Ext").mkdir(parents=True)
        (root / "CommonModules" / "Обычный.xml").write_text(
            "<CommonModule><Name>Обычный</Name></CommonModule>", encoding="utf-8"
        )
        (root / "CommonModules" / "Привилегированный.xml").write_text(
            "<CommonModule><Name>Привилегированный</Name><Privileged>true</Privileged></CommonModule>",
            encoding="utf-8",
        )
        ordinary_module = root / "CommonModules" / "Обычный" / "Ext" / "Module.bsl"
        ordinary_module.write_text(
            "Процедура НетЭкспорта()\n    Привилегированный.Отсутствующий();\nКонецПроцедуры\n",
            encoding="utf-8",
        )
        (root / "CommonModules" / "Привилегированный" / "Ext" / "Module.bsl").write_text(
            "Процедура Метод() Экспорт\nКонецПроцедуры\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "onec_hbk_bsl.analysis.diagnostics._common_module_privileged_map_cached",
            lambda *_args, **_kwargs: pytest.fail(
                "privileged index is not expected for BSL213-only run"
            ),
        )
        diags = DiagnosticEngine(select={"BSL213"}).check_file(str(ordinary_module))
        assert "BSL213" in _codes(diags)

    def test_bsl213_loads_only_called_common_modules(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = tmp_path / "Config"
        root.mkdir(parents=True)
        (root / "Configuration.xml").write_text("<Configuration/>", encoding="utf-8")
        for module_name in ("Caller", "Target", "Unused"):
            (root / "CommonModules" / module_name / "Ext").mkdir(parents=True)
            (root / "CommonModules" / f"{module_name}.xml").write_text(
                f"<CommonModule><Name>{module_name}</Name></CommonModule>", encoding="utf-8"
            )
        caller_module = root / "CommonModules" / "Caller" / "Ext" / "Module.bsl"
        caller_module.write_text(
            "Процедура Run()\n    Target.Absent();\nКонецПроцедуры\n",
            encoding="utf-8",
        )
        (root / "CommonModules" / "Target" / "Ext" / "Module.bsl").write_text(
            "Процедура Exists() Экспорт\nКонецПроцедуры\n",
            encoding="utf-8",
        )
        (root / "CommonModules" / "Unused" / "Ext" / "Module.bsl").write_text(
            "Процедура NeverUsed() Экспорт\nКонецПроцедуры\n",
            encoding="utf-8",
        )

        import onec_hbk_bsl.analysis.diagnostics as diagnostics_mod

        original = diagnostics_mod._common_module_proc_names_for_module_cached
        calls: set[str] = set()

        def spy(config_root: str, module_name_cf: str) -> frozenset[str]:
            calls.add(module_name_cf)
            return original(config_root, module_name_cf)

        monkeypatch.setattr(
            "onec_hbk_bsl.analysis.diagnostics._common_module_proc_names_for_module_cached",
            spy,
        )
        diags = DiagnosticEngine(select={"BSL213"}).check_file(str(caller_module))
        assert "BSL213" in _codes(diags)
        assert "target" in calls
        assert "unused" not in calls

    def test_external_resource_timeout_tail_rule(self, tmp_path: Path) -> None:
        diags = _check(
            """\
            Процедура Метод()
                Соединение = Новый HTTPСоединение("x", 80, "u", "p");
            КонецПроцедуры
            """,
            tmp_path,
            select={"BSL253"},
        )
        assert "BSL253" in _codes(diags)


# ---------------------------------------------------------------------------
# BSL171 / BSL204 / BSL217 / BSL248 / BSL251 / BSL252 / BSL259 / BSL268
# ---------------------------------------------------------------------------


class TestBsl204InvalidCharacterInFile:
    def test_escaped_quote_string_span(self, tmp_path: Path) -> None:
        content = 'Процедура Тест()\n\tНСтр("ru=\'текст "" – хвост\'") +\nКонецПроцедуры\n'
        diags = _check(content, tmp_path, select={"BSL204"})
        bsl204 = [d for d in diags if d.code == "BSL204"]
        assert len(bsl204) == 1
        assert bsl204[0].line == 2
        assert bsl204[0].character == content.splitlines()[1].index('"')
        assert bsl204[0].end_character == content.splitlines()[1].rindex('"') + 1


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
        assert bsl228[0].message == "Переместите необязательные параметры после обязательных"
        assert bsl228[0].character == line.index("(") + 1
        assert bsl228[0].end_character == line.rindex(")")


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
        assert bsl003[0].character == 10
        assert bsl003[0].message == (
            'Переместите неэкспортный метод "МоеАПИ" из области "ПрограммныйИнтерфейс"'
        )

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
    def test_url_not_detected(self, tmp_path: Path) -> None:
        # BSLLS does not flag URLs via BSL005 (only bare IPv4 and UNC paths)
        content = 'Адрес = "http://example.com/api";\n'
        diags = _check(content, tmp_path)
        assert "BSL005" not in _codes(diags)

    def test_ip_address_detected(self, tmp_path: Path) -> None:
        content = 'Адрес = "192.168.1.100";\n'
        diags = _check(content, tmp_path)
        assert "BSL005" in _codes(diags)

    def test_no_hardcode_no_warning(self, tmp_path: Path) -> None:
        content = "Адрес = ПолучитьАдрес();\n"
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

    def test_module_var_assignment_is_not_local_unused(self, tmp_path: Path) -> None:
        content = """\
            Перем КоординатыВыделения;

            Процедура Тест()
                КоординатыВыделения = Новый Структура;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL007"})
        assert "BSL007" not in _codes(diags)

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
        assert "Элемент" in diags[0].message

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
        assert "ИмяСобытия" in diags[0].message

    def test_member_access_name_does_not_count_as_local_read(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Вложения = ПолучитьВложения();
                Сообщить(ПочтовоеСообщение.Вложения);
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL007"}) if d.code == "BSL007"]
        assert len(diags) == 1
        assert "Вложения" in diags[0].message

    def test_string_assignment_unused_is_not_filtered_out(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                ИмяСобытия = "Проверка подписи";
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL007"}) if d.code == "BSL007"]
        assert len(diags) == 1
        assert "ИмяСобытия" in diags[0].message


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
        diags = _check(content, tmp_path, max_returns=3, select={"BSL008"})
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
        assert bsl009[0].message == "Удалите бесполезное присваивание переменной самой себе"

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
        assert bsl011[0].message.startswith('Уменьшите когнитивную сложность "Сложная" с ')

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
        assert bsl011[0].message == 'Уменьшите когнитивную сложность "Сложная" с 6 до 5'

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
        assert bsl011[0].message == 'Уменьшите когнитивную сложность "Сложная" с 1 до 0'


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
        content = """\
            // TODO: реализовать
            Процедура Тест()
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL013"})
        assert "BSL013" not in _codes(diags)

    def test_single_commented_expression_detected(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Результат = НСтр("ru='До '") +
                //НСтр("ru='Закомментировано '") +
                НСтр("ru='После'");
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL013"})
        bsl013 = [d for d in diags if d.code == "BSL013"]
        assert len(bsl013) == 1
        assert bsl013[0].line == 3
        assert bsl013[0].character == 4

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

    def test_embedded_expression_in_comment_group_detected(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                // Специальная обработка автоматически задаваемого номера:
                // "Приложение" - в случае ВРег(СокрЛП(ИмяФормы)) = ВРег("ФормаОтчета2025Кв1")
                Сообщить("OK");
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL013"})
        bsl013 = [d for d in diags if d.code == "BSL013"]
        assert len(bsl013) == 1
        assert bsl013[0].line == 2
        assert bsl013[0].end_line == 3


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
        assert bsl014[0].message == "Длина строки 130 превышает максимально допустимую 80"

    def test_short_line_no_warning(self, tmp_path: Path) -> None:
        content = "Процедура Тест()\n    А = 1;\nКонецПроцедуры\n"
        diags = _check(content, tmp_path, max_line_length=120)
        assert "BSL014" not in _codes(diags)

    def test_trailing_spaces_do_not_count_in_bslls_message(self, tmp_path: Path) -> None:
        content = "Процедура Тест()\n\tА = 12345678901234567890;   \nКонецПроцедуры\n"
        diags = _check(content, tmp_path, max_line_length=25, select={"BSL014"})
        bsl014 = [d for d in diags if d.code == "BSL014"]
        assert len(bsl014) == 1
        assert bsl014[0].message == "Длина строки 26 превышает максимально допустимую 25"


# ---------------------------------------------------------------------------
# BSL015 — NumberOfOptionalParams
# ---------------------------------------------------------------------------


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
        path = tmp_path / "AccumulationRegisters" / "Foo" / "Ext" / "ManagerModule.bsl"
        path.parent.mkdir(parents=True)
        path.write_text(textwrap.dedent(content), encoding="utf-8")
        diags = DiagnosticEngine(select={"BSL016"}).check_file(str(path))
        bsl016 = [d for d in diags if d.code == "BSL016"]
        assert len(bsl016) >= 1
        assert 'Нужно удалить нестандартный раздел "МояНестандартнаяОбласть"' == bsl016[0].message

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
            'ТоженПароль = "МойПароль123@#";\n'  # line 4 → reported
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
            'Токен = "abc";\n'  # BSL012 fires, BSL014 still off
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
        from onec_hbk_bsl.analysis.diagnostics import _BSLLS_NAME_TO_CODE, RULE_METADATA

        assert set(RULE_METADATA) == set(_BSLLS_NAME_TO_CODE.values())

    def test_metadata_has_required_fields(self) -> None:
        from onec_hbk_bsl.analysis.diagnostics import RULE_METADATA

        required = {"name", "description", "severity", "sonar_type", "sonar_severity"}
        for code, meta in RULE_METADATA.items():
            missing = required - set(meta.keys())
            assert not missing, f"{code} is missing fields: {missing}"

    def test_all_bsl041_rules_have_metadata(self) -> None:
        from onec_hbk_bsl.analysis.diagnostics import _BSLLS_NAME_TO_CODE, RULE_METADATA

        assert len(RULE_METADATA) == len(set(_BSLLS_NAME_TO_CODE.values()))


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
        assert bsl019[0].message.startswith('Уменьшите цикломатическую сложность "Сложная" с ')

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

    def test_function_call_parentheses_do_not_duplicate_boolean_cost(
        self, tmp_path: Path
    ) -> None:
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
        assert (
            diags[0].message == "Выделите условие оператора Если в отдельный метод или переменную"
        )


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

    def test_hack_not_detected(self, tmp_path: Path) -> None:
        # BSLLS default UsingServiceTag pattern does not include HACK
        content = "// HACK: временный обходной путь\nА = 1;\n"
        diags = _check(content, tmp_path)
        assert "BSL023" not in _codes(diags)

    def test_normal_comment_no_warning(self, tmp_path: Path) -> None:
        content = "// Обычный комментарий без тегов\nА = 1;\n"
        diags = _check(content, tmp_path)
        assert "BSL023" not in _codes(diags)

    def test_tag_inside_string_literal_no_warning(self, tmp_path: Path) -> None:
        content = 'Сообщение = "строка // TODO: не комментарий";\n'
        diags = _check(content, tmp_path, select={"BSL023"})
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

    def test_doc_comment_slash3_with_text_warns(self, tmp_path: Path) -> None:
        """BSLLS strict flags triple-slash comments when text follows without a space after ``//``."""
        content = "/// Документация функции\nА = 1;\n"
        diags = _check(content, tmp_path)
        assert "BSL024" in _codes(diags)

    def test_empty_comment_no_warning(self, tmp_path: Path) -> None:
        """An empty // comment (nothing after) is OK."""
        content = "//\nА = 1;\n"
        diags = _check(content, tmp_path)
        assert "BSL024" not in _codes(diags)

    def test_multiple_slashes_only_no_warning(self, tmp_path: Path) -> None:
        """BSLLS strict: ``////`` and ``///`` are valid without a space after ``//``."""
        content = "////\n///\nА = 1;\n"
        diags = _check(content, tmp_path, select={"BSL024"})
        assert "BSL024" not in _codes(diags)

    def test_at_annotation_no_warning(self, tmp_path: Path) -> None:
        content = "//@УстановитьОбработчик\nА = 1;\n"
        diags = _check(content, tmp_path, select={"BSL024"})
        assert "BSL024" not in _codes(diags)

    def test_compiler_directive_no_bsl024(self, tmp_path: Path) -> None:
        """``//&НаКлиенте`` — BSLLS does not flag SpaceAtStartComment."""
        content = "//&НаКлиенте\nА = 1;\n"
        diags = _check(content, tmp_path, select={"BSL024"})
        assert "BSL024" not in _codes(diags)

    def test_asterisk_banner_reports_bsl024(self, tmp_path: Path) -> None:
        """BSLLS SpaceAtStartComment flags decorative ``//****`` lines (parity on real EDT modules)."""
        content = "//**********************************************\nА = 1;\n"
        diags = _check(content, tmp_path, select={"BSL024"})
        assert "BSL024" in _codes(diags)

    def test_commented_code_line_no_bsl024(self, tmp_path: Path) -> None:
        """BSLLS skips SpaceAtStartComment when comment looks like code (CodeRecognizer)."""
        content = "//  Х = 1;\nА = 1;\n"
        diags = _check(content, tmp_path, select={"BSL024"})
        assert "BSL024" not in _codes(diags)

    def test_commented_call_no_bsl024(self, tmp_path: Path) -> None:
        content = "//НСтр(\"ru='строка'\") +\nА = 1;\n"
        diags = _check(content, tmp_path, select={"BSL024"})
        assert "BSL024" not in _codes(diags)

    def test_commented_if_no_bsl024(self, tmp_path: Path) -> None:
        content = "//Если Условие Тогда\n//КонецЕсли;\nА = 1;\n"
        diags = _check(content, tmp_path, select={"BSL024"})
        assert "BSL024" not in _codes(diags)

    def test_query_pipe_comment_reports_bsl024(self, tmp_path: Path) -> None:
        content = "//|\tИ Поле = &Поле\nА = 1;\n"
        diags = _check(content, tmp_path, select={"BSL024"})
        assert "BSL024" in _codes(diags)

    def test_inline_comment_without_space_reports(self, tmp_path: Path) -> None:
        content = "Перем1 = 7; //И это плохо\n"
        diags = _check(content, tmp_path, select={"BSL024"})
        bsl024 = [d for d in diags if d.code == "BSL024"]
        assert len(bsl024) == 1
        assert bsl024[0].character == content.index("//")
        assert (
            bsl024[0].message
            == "Между символами комментария '//' и самим текстом комментария должен быть пробел."
        )

    def test_four_slashes_with_text_reports(self, tmp_path: Path) -> None:
        content = "////Текст с ошибкой\n"
        diags = _check(content, tmp_path, select={"BSL024"})
        assert "BSL024" in _codes(diags)


# ---------------------------------------------------------------------------
# BSL200 — IncorrectLineBreak
# ---------------------------------------------------------------------------


class TestBsl200IncorrectLineBreak:
    def test_line_ending_with_plus_reports(self, tmp_path: Path) -> None:
        content = """\
            Сумма = Часть1 +
                Часть2;
        """
        diags = _check(content, tmp_path, select={"BSL200"})
        bsl200 = [d for d in diags if d.code == "BSL200"]
        assert bsl200
        assert (
            bsl200[0].message
            == "Проверьте правильность переноса операндов, операторов и параметров"
        )

    def test_line_starting_with_comma_reports(self, tmp_path: Path) -> None:
        content = """\
            Имена.Добавить(Первый
                , Второй);
        """
        diags = _check(content, tmp_path, select={"BSL200"})
        assert "BSL200" in _codes(diags)

    def test_line_starting_with_comma_after_open_string_reports(self, tmp_path: Path) -> None:
        content = """\
            Имена.Вставить("Первый"
                , Второй);
        """
        diags = _check(content, tmp_path, select={"BSL200"})
        assert [
            (d.line, d.character, d.end_line, d.end_character) for d in diags if d.code == "BSL200"
        ] == [
            (2, 4, 2, 14),
        ]

    def test_query_assignment_before_query_text_is_skipped(self, tmp_path: Path) -> None:
        content = """\
            Запрос.Текст =
                "ВЫБРАТЬ
                | Истина";
        """
        diags = _check(content, tmp_path, select={"BSL200"})
        assert "BSL200" not in _codes(diags)

    def test_operator_inside_string_is_skipped(self, tmp_path: Path) -> None:
        content = 'Сообщить("Строка +");\n'
        diags = _check(content, tmp_path, select={"BSL200"})
        assert "BSL200" not in _codes(diags)

    def test_comment_suffix_is_skipped(self, tmp_path: Path) -> None:
        content = """\
            Значение = Истина; // ИЛИ
        """
        diags = _check(content, tmp_path, select={"BSL200"})
        assert "BSL200" not in _codes(diags)

    def test_matches_bslls_fixture(self) -> None:
        fixture = Path(
            ".agent/tmp/bslls-source/src/test/resources/diagnostics/IncorrectLineBreakDiagnostic.bsl"
        )
        if not fixture.exists():
            pytest.skip("BSLLS fixture is not available")
        diags = [
            diag
            for diag in DiagnosticEngine(select={"BSL200"}).check_file(str(fixture))
            if diag.code == "BSL200"
        ]
        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (7, 32, 7, 33),
            (8, 35, 8, 36),
            (16, 32, 16, 33),
            (17, 22, 17, 23),
            (21, 49, 21, 50),
            (45, 25, 45, 76),
            (47, 25, 47, 79),
            (59, 4, 59, 55),
            (61, 4, 61, 58),
            (70, 80, 70, 83),
            (83, 89, 83, 92),
            (102, 2, 102, 3),
            (106, 2, 106, 3),
            (110, 2, 110, 3),
        ]


class TestBsl216MissingSpace:
    def test_semicolon_before_comment_reports_even_with_comment_slash(self, tmp_path: Path) -> None:
        content = 'ПотокXML.ЗаписатьКонецЭлемента();// "ФИО"\n'
        diags = _check(content, tmp_path, select={"BSL216"})
        assert [(d.line, d.character, d.message) for d in diags if d.code == "BSL216"] == [
            (1, 32, "Справа от ';' не хватает пробела"),
        ]

    def test_comma_before_string_reports_when_plus_is_inside_string(self, tmp_path: Path) -> None:
        content = 'Результат = ?(Настройки.Погрешность," ± " + Погрешность, "");\n'
        diags = _check(content, tmp_path, select={"BSL216"})
        assert [(d.line, d.character, d.message) for d in diags if d.code == "BSL216"] == [
            (1, 35, "Справа от ',' не хватает пробела"),
        ]


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

    def test_message_matches_bslls_style(self, tmp_path: Path) -> None:
        content = """\
            Функция Тест()
                Возврат 9 + 1;
            КонецФункции
        """
        diags = _check(content, tmp_path, select={"BSL029"})
        diag = next(d for d in diags if d.code == "BSL029")
        assert (
            diag.message
            == 'Создайте константу с понятным названием, присвойте ей значение "9" и используйте эту константу вместо магического числа.'
        )

    def test_decimal_less_than_one_detected(self, tmp_path: Path) -> None:
        content = """\
            Функция Тест()
                Возврат 0.15;
            КонецФункции
        """
        diags = _check(content, tmp_path, select={"BSL029"})
        assert "BSL029" in _codes(diags)

    def test_array_index_literal_not_flagged(self, tmp_path: Path) -> None:
        content = """\
            Функция Тест(Массив)
                Возврат Массив[2];
            КонецФункции
        """
        diags = _check(content, tmp_path, select={"BSL029"})
        assert "BSL029" not in _codes(diags)

    def test_insert_call_on_non_structure_is_flagged(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Данные.Вставить("ПрПодп", 2);
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL029"})
        assert "BSL029" in _codes(diags)

    def test_known_structure_and_map_insert_values_are_skipped(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                СтруктураДанных = Новый Структура;
                СтруктураДанных.Вставить("Код", 42);
                СтруктураДанных.Вставить(ПолучитьКлюч(), 100);
                СоответствиеДанных = Новый Соответствие;
                СоответствиеДанных.Вставить(2024, 19242);
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL029"})
        assert "BSL029" not in _codes(diags)

    def test_nested_numeric_inside_ternary_branch_is_reported(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Телефон = ?(СтрНачинаетсяС(Телефон, "+7"), "8" + Сред(Телефон, 3), Телефон);
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL029"})
        assert [(d.line, d.character, d.end_character) for d in diags if d.code == "BSL029"] == [
            (2, 67, 68),
        ]

    def test_matches_bslls_fixture(self) -> None:
        fixture = Path(
            ".agent/tmp/bslls-source/src/test/resources/diagnostics/MagicNumberDiagnostic.bsl"
        )
        if not fixture.exists():
            pytest.skip("BSLLS fixture is not available")
        diags = [
            diag
            for diag in DiagnosticEngine(select={"BSL029"}).check_file(str(fixture))
            if diag.code == "BSL029"
        ]
        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (4, 18, 4, 20),
            (4, 23, 4, 25),
            (8, 31, 8, 33),
            (12, 20, 12, 21),
            (21, 21, 21, 23),
            (24, 24, 24, 26),
            (28, 34, 28, 35),
            (34, 37, 34, 38),
            (35, 37, 35, 38),
            (45, 12, 45, 14),
        ]


# ---------------------------------------------------------------------------
# BSL030 — SemicolonPresence (missing statement semicolon)
# ---------------------------------------------------------------------------


class TestBsl030HeaderSemicolon:
    def test_semicolon_on_header_is_empty_statement_not_bsl030(self, tmp_path: Path) -> None:
        content = "Процедура Тест();\nКонецПроцедуры\n"
        diags = _check(content, tmp_path)
        assert "BSL030" not in _codes(diags)
        assert "BSL025" in _codes(diags)

    def test_no_semicolon_no_warning(self, tmp_path: Path) -> None:
        content = "Процедура Тест()\nКонецПроцедуры\n"
        diags = _check(content, tmp_path)
        assert "BSL030" not in _codes(diags)

    def test_export_with_semicolon_is_empty_statement_not_bsl030(self, tmp_path: Path) -> None:
        content = "Процедура Тест() Экспорт;\nКонецПроцедуры\n"
        diags = _check(content, tmp_path)
        assert "BSL030" not in _codes(diags)
        assert "BSL025" in _codes(diags)


# ---------------------------------------------------------------------------
# BSL031 — NumberOfParams
# ---------------------------------------------------------------------------


class TestBsl031NumberOfParams:
    def test_too_many_params_detected(self, tmp_path: Path) -> None:
        content = "Процедура Тест(А, Б, В, Г, Д, Е, Ж, З)\nКонецПроцедуры\n"
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
                Для Каждого Элемент Из Коллекция Цикл
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
        bsl035 = [d for d in diags if d.code == "BSL035"]
        assert bsl035
        assert (
            bsl035[0].message
            == 'Необходимо избавиться от многократного использования строкового литерала "ОченьДлиннаяСтрока"'
        )

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

    def test_same_literal_in_different_procedures_no_warning(self, tmp_path: Path) -> None:
        """Repeated structure keys like Вставить("Ключ") across methods are not duplicates."""
        content = """\
            Функция Один() Экспорт
                Р = Новый Структура;
                Р.Вставить("ОченьДлиннаяСтрока", 1);
                Возврат Р;
            КонецФункции

            Функция Два() Экспорт
                Р = Новый Структура;
                Р.Вставить("ОченьДлиннаяСтрока", 2);
                Возврат Р;
            КонецФункции

            Функция Три() Экспорт
                Р = Новый Структура;
                Р.Вставить("ОченьДлиннаяСтрока", 3);
                Возврат Р;
            КонецФункции
        """
        diags = _check(content, tmp_path, min_duplicate_uses=3)
        assert "BSL035" not in _codes(diags)

    def test_adjacent_string_accesses_do_not_create_pseudo_literals(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест(Запрос)
                Параметры.Вставить("ID", Запрос["ПараметрыURL"].Получить("ID"));
                Параметры.Вставить("ID", Запрос["ПараметрыURL"].Получить("ID"));
                Параметры.Вставить("ID", Запрос["ПараметрыURL"].Получить("ID"));
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, min_duplicate_uses=3, select={"BSL035"})
        messages = [d.message for d in diags if d.code == "BSL035"]
        assert all('", Запрос["' not in message for message in messages)
        assert all('"].Получить("' not in message for message in messages)

    def test_escaped_quotes_are_part_of_literal(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                А = "Код ""240"" места";
                Б = "Код ""240"" места";
                В = "Код ""240"" места";
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, min_duplicate_uses=3, select={"BSL035"})
        bsl035 = [d for d in diags if d.code == "BSL035"]
        assert [(d.line, d.character, d.end_character) for d in bsl035] == [(2, 8, 27)]
        assert bsl035[0].message == (
            'Необходимо избавиться от многократного использования строкового литерала "Код ""240"" места"'
        )

    def test_duplicate_grouping_is_case_insensitive(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                А = "Раздел";
                Б = "раздел";
                В = "Раздел";
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, min_duplicate_uses=3, select={"BSL035"})
        bsl035 = [d for d in diags if d.code == "BSL035"]
        assert len(bsl035) == 1
        assert bsl035[0].message == (
            'Необходимо избавиться от многократного использования строкового литерала "Раздел"'
        )


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
        assert "BSL036" in _codes(diags)

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


# ---------------------------------------------------------------------------
# BSL153 — CanonicalSpelling (form module parity)
# ---------------------------------------------------------------------------


class TestBsl153FormModuleSkips:
    def test_form_module_path_skips_bsl153(self, tmp_path: Path) -> None:
        """BSLLS parity: EDT form ``Module.bsl`` — skip canonical keyword spelling (BSL153)."""
        content = """\
            процедура Тест()
                А = 1;
            КонецПроцедуры
        """
        form_dir = tmp_path / "Forms" / "SomeForm" / "Ext"
        form_dir.mkdir(parents=True)
        bsl_path = form_dir / "Module.bsl"
        bsl_path.write_text(textwrap.dedent(content), encoding="utf-8")
        diags = DiagnosticEngine(select={"BSL153"}).check_file(str(bsl_path))
        assert "BSL153" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL208 / BSL256 — Latin+Cyrillic vs Typo (homoglyph), BSLLS priority
# ---------------------------------------------------------------------------


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
                ИмяName = 1;
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
        assert diags[0].message == 'Возможная опечатка в "Поздниее"'

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
        assert diags[0].message == 'Возможная опечатка в "Поздниее"'

    def test_bslls_typo_skips_exception_fragment_and_reports_next(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            "onec_hbk_bsl.analysis.bslls_typo.default_spell_fn",
            lambda word: word in {"Сис", "Инфо"},
        )
        content = 'Процедура Тест()\n    Сообщить("СисИнфо");\nКонецПроцедуры\n'
        path = tmp_path / "TypoFirstFragment.bsl"
        path.write_text(content, encoding="utf-8")

        diags = [
            d
            for d in DiagnosticEngine(select={"BSL256"}).check_file(str(path))
            if d.code == "BSL256"
        ]
        assert len(diags) == 1
        assert diags[0].message == 'Возможная опечатка в "Инфо"'

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
        assert diags[0].message == 'Возможная опечатка в "Атмена"'

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
        assert messages == {'Возможная опечатка в "Физлица"'}

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


# ---------------------------------------------------------------------------
# BSL039 — NestedTernaryOperator
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# BSL041 — DeprecatedMessage
# ---------------------------------------------------------------------------


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
# BSL047 — MagicDate
# ---------------------------------------------------------------------------


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

    def test_elseif_true_detected_via_cst(self, tmp_path: Path) -> None:
        """ИначеЕсли Истина — отдельный узел elseif_clause в CST."""
        content = """\
            Процедура Т()
                Если А = 1 Тогда
                ИначеЕсли Истина Тогда
                КонецЕсли;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL052"})
        assert "BSL052" in _codes(diags)
        lines = {d.line for d in diags if d.code == "BSL052"}
        assert 3 in lines  # ИначеЕсли line (1-based)

    def test_bsl052_cst_helpers_match_parser(self, tmp_path: Path) -> None:
        from onec_hbk_bsl.analysis.diagnostics import _bsl052_collect_literal_if_nodes
        from onec_hbk_bsl.parser.bsl_parser import BslParser

        content = """\
            Процедура Т()
                Если А = 1 Тогда
                ИначеЕсли Истина Тогда
                КонецЕсли;
            КонецПроцедуры
        """
        tree = BslParser().parse_content(content)
        pairs: list[tuple[int, str]] = []
        _bsl052_collect_literal_if_nodes(tree.root_node, pairs)
        assert pairs == [(2, "Истина")]


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# BSL054 — ModuleLevelVariable
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# BSL040 — UsingThisForm (form module path detection)
# ---------------------------------------------------------------------------


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

    def test_path_is_likely_form_module_bsl(self, tmp_path: Path) -> None:
        mod = tmp_path / "Forms" / "SomeForm" / "Ext" / "Module.bsl"
        mod.parent.mkdir(parents=True)
        mod.write_text("// ok\n", encoding="utf-8")
        assert path_is_likely_form_module_bsl(str(mod))
        plain = tmp_path / "CommonModules" / "Foo" / "Ext" / "Module.bsl"
        plain.parent.mkdir(parents=True)
        plain.write_text("// ok\n", encoding="utf-8")
        assert not path_is_likely_form_module_bsl(str(plain))


# ---------------------------------------------------------------------------
# BSL219 — MissingVariablesDescription
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# BSL234 — QueryNestedFieldsByDot
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# BSL258 — UnionAll
# ---------------------------------------------------------------------------


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

    def test_matches_bslls_fixture(self) -> None:
        fixture = (
            Path(".agent/tmp/bslls-source/src/test/resources/diagnostics")
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

    def test_two_blank_lines_detected_bslls_parity(self, tmp_path: Path) -> None:
        """BSLLS flags 2+ consecutive empty lines (max one blank between statements)."""
        content = "А = 1;\n\n\nБ = 2;\n"
        bsl_file = tmp_path / "test.bsl"
        bsl_file.write_text(content, encoding="utf-8")
        diags = DiagnosticEngine(select={"BSL055"}).check_file(str(bsl_file))
        assert "BSL055" in _codes(diags)

    def test_single_blank_line_no_warning(self, tmp_path: Path) -> None:
        content = "А = 1;\n\nБ = 2;\n"
        bsl_file = tmp_path / "test.bsl"
        bsl_file.write_text(content, encoding="utf-8")
        diags = DiagnosticEngine(select={"BSL055"}).check_file(str(bsl_file))
        assert "BSL055" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL149 — AssignAliasFieldsInQuery
# ---------------------------------------------------------------------------


class TestBsl149AssignAliasFieldsInQueryFixture:
    def test_multiline_select_without_alias_detected(self, tmp_path: Path) -> None:
        content = """\
            ТекстЗапроса = "ВЫБРАТЬ
            |   Код,
            |   Наименование
            |ИЗ
            |   Справочник.Номенклатура";
        """
        diags = _check(content, tmp_path, select={"BSL149"})
        assert "BSL149" in _codes(diags)

    def test_multiline_select_with_alias_no_warning(self, tmp_path: Path) -> None:
        content = """\
            ТекстЗапроса = "ВЫБРАТЬ
            |   Код КАК Код,
            |   Наименование КАК Наименование
            |ИЗ
            |   Справочник.Номенклатура";
        """
        diags = _check(content, tmp_path, select={"BSL149"})
        assert "BSL149" not in _codes(diags)

    def test_single_line_select_without_alias_detected(self, tmp_path: Path) -> None:
        content = 'А = "ВЫБРАТЬ Ссылка, Номер ИЗ Документ.РасходнаяНакладная";\n'
        diags = _check(content, tmp_path, select={"BSL149"})
        assert "BSL149" in _codes(diags)

    def test_single_line_select_with_alias_no_warning(self, tmp_path: Path) -> None:
        content = 'А = "ВЫБРАТЬ Ссылка КАК С, Номер КАК Н ИЗ Документ.РасходнаяНакладная";\n'
        diags = _check(content, tmp_path, select={"BSL149"})
        assert "BSL149" not in _codes(diags)

    def test_select_star_no_warning(self, tmp_path: Path) -> None:
        content = 'А = "ВЫБРАТЬ * ИЗ Документ.РасходнаяНакладная";\n'
        diags = _check(content, tmp_path, select={"BSL149"})
        assert "BSL149" not in _codes(diags)

    def test_reports_field_span_and_specific_message(self, tmp_path: Path) -> None:
        content = """\
            ТекстЗапроса = "ВЫБРАТЬ
            |   ТранспортноеСообщение.Ссылка
            |ИЗ
            |   Документ.ТранспортноеСообщение КАК ТранспортноеСообщение";
        """
        diags = _check(content, tmp_path, select={"BSL149"})
        bsl149 = [d for d in diags if d.code == "BSL149"]
        assert len(bsl149) == 1
        assert bsl149[0].line == 2
        assert bsl149[0].character > 0
        assert "ТранспортноеСообщение.Ссылка" in bsl149[0].message

    def test_multiline_case_with_alias_no_warning(self, tmp_path: Path) -> None:
        content = """\
            ТекстЗапроса = "ВЫБРАТЬ
            |   ВЫБОР
            |       КОГДА Т.Сумма > 0
            |           ТОГДА 1
            |       ИНАЧЕ 0
            |   КОНЕЦ КАК Признак,
            |   Т.Ссылка КАК Ссылка
            |ИЗ
            |   Документ.РасходнаяНакладная КАК Т";
        """
        diags = _check(content, tmp_path, select={"BSL149"})
        assert "BSL149" not in _codes(diags)

    def test_case_continuation_without_alias_no_warning(self, tmp_path: Path) -> None:
        content = """\
            ТекстЗапроса = "ВЫБРАТЬ
            |   ВЫБОР
            |       КОГДА Т.Проведен
            |           ТОГДА Т.Сумма
            |       ИНАЧЕ 0
            |   КОНЕЦ,
            |   Т.Ссылка КАК Ссылка
            |ИЗ
            |   Документ.РасходнаяНакладная КАК Т";
        """
        diags = _check(content, tmp_path, select={"BSL149"})
        assert "BSL149" not in _codes(diags)

    def test_where_condition_connectors_are_not_treated_as_select_fields(
        self, tmp_path: Path
    ) -> None:
        content = """\
            ТекстЗапроса = "ВЫБРАТЬ
            |   Т.Ссылка КАК Ссылка
            |ИЗ
            |   Документ.РасходнаяНакладная КАК Т
            |ГДЕ
            |   Т.Проведен
            |   И Т.ПометкаУдаления = ЛОЖЬ
            |   ИЛИ Т.Номер = 0";
        """
        diags = _check(content, tmp_path, select={"BSL149"})
        assert "BSL149" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL210 — LogicalOrInTheWhereSectionOfQuery
# ---------------------------------------------------------------------------


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

    def test_matches_bslls_fixture(self) -> None:
        fixture = Path(
            ".agent/tmp/bslls-source/src/test/resources/diagnostics/"
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

    def test_unused_parameters_skipped_in_client_command_handler(self, tmp_path: Path) -> None:
        """Колбэк Параметры в типовом ОбработкаКоманды на клиенте — не BSL062 (как BSLLS на командах)."""
        content = """\
            &НаКлиенте
            Процедура ОбработкаКоманды(ПараметрКоманды, ПараметрыВыполненияКоманды, Параметры)
                А = 1;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL062"})
        assert "BSL062" not in _codes(diags)

    def test_unused_parameters_skipped_in_notify_completion_handler(self, tmp_path: Path) -> None:
        """Второй параметр Параметры в экспортном *Завершение — штатный колбэк оповещения."""
        content = """\
            &НаКлиенте
            Процедура МояОперацияЗавершение(Результат, Параметры) Экспорт
                А = Результат;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL062"})
        assert "BSL062" not in _codes(diags)

    def test_optional_param_not_flagged(self, tmp_path: Path) -> None:
        """Параметры с дефолтным значением (= Неопределено) не флагуются как BSL062."""
        content = """\
            Функция ВычислитьЦену(Количество, Скидка = 0, Валюта = Неопределено)
                Возврат Количество;
            КонецФункции
        """
        diags = _check(content, tmp_path, select={"BSL062"})
        assert "BSL062" not in _codes(diags)

    def test_command_param_not_flagged(self, tmp_path: Path) -> None:
        """Параметр Команда в командных обработчиках формы не флагуется."""
        content = """\
            &НаКлиенте
            Процедура Сохранить(Команда)
                А = 1;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL062"})
        assert "BSL062" not in _codes(diags)

    def test_dopolnitelnye_parametry_not_flagged(self, tmp_path: Path) -> None:
        """ДополнительныеПараметры в колбэках ОписаниеОповещения не флагуются."""
        content = """\
            &НаКлиенте
            Процедура ОткрытьЗавершение(Отказ, ДополнительныеПараметры) Экспорт
                Сообщить("ok");
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL062"})
        assert "BSL062" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL254 — TransferringParametersBetweenClientAndServer
# ---------------------------------------------------------------------------


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
        assert (
            diags[0].message == 'Установите модификатор "Знач" для параметра Документ метода Сервер'
        )

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
            'Установите модификатор "Знач" для параметра Адрес метода Сервер',
            'Установите модификатор "Знач" для параметра ВыводитьОшибку метода Сервер',
            'Установите модификатор "Знач" для параметра ТипАрхива метода Сервер',
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


# ---------------------------------------------------------------------------
# BSL218 — MissingTemporaryFileDeletion
# ---------------------------------------------------------------------------


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

    def test_matches_bslls_fixture(self) -> None:
        fixture = (
            Path(".agent/tmp/bslls-source/src/test/resources/diagnostics")
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


# ---------------------------------------------------------------------------
# BSL225 — NumberOfValuesInStructureConstructor
# ---------------------------------------------------------------------------


class TestBsl225NumberOfValuesInStructureConstructor:
    def test_structure_with_too_many_values_is_reported(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Данные = Новый Структура("Ключ1,Ключ2,Ключ3,Ключ4", 1, 2, 3, 4);
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL225"})
        assert _codes(diags) == ["BSL225"]
        assert (
            diags[0].message
            == "Уменьшите количество значений свойств, передаваемых в конструктор структуры"
        )

    def test_structure_with_three_values_is_clean(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Данные = Новый Структура("Ключ1,Ключ2,Ключ3", 1, 2, 3);
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL225"})
        assert "BSL225" not in _codes(diags)


# ---------------------------------------------------------------------------
# BSL245 — ServerSideExportFormMethod
# ---------------------------------------------------------------------------


class TestBsl245ServerSideExportFormMethod:
    def test_server_export_in_form_module_is_reported(self, tmp_path: Path) -> None:
        content = """\
            &НаСервере
            Процедура ПолучитьДанные() Экспорт
            КонецПроцедуры
        """
        path = tmp_path / "Forms" / "ФормаСписка" / "Ext" / "Form" / "Module.bsl"
        path.parent.mkdir(parents=True)
        path.write_text(textwrap.dedent(content), encoding="utf-8")
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
        diags = DiagnosticEngine(select={"BSL245"}).check_file(str(path))
        assert "BSL245" not in _codes(diags)


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
# BSL065 — MissingReturnedValueDescription
# ---------------------------------------------------------------------------


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
        assert diags[0].message == "Удалите описание возвращаемого значения для процедуры"

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


# ---------------------------------------------------------------------------
# BSL240 — RewriteMethodParameter (parameter default lines are not body)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# BSL066 — DeprecatedFind (BSLLS parity: only Найти() → СтрНайти())
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# BSL131 — DuplicateRegion
# ---------------------------------------------------------------------------


class TestBsl131DuplicateRegion:
    def test_duplicate_region_detected(self, tmp_path: Path) -> None:
        content = (
            "#Область Публичный\nА = 1;\n#КонецОбласти\n#Область Public\nБ = 2;\n#КонецОбласти\n"
        )
        p = tmp_path / "test.bsl"
        p.write_text(content, encoding="utf-8")
        from onec_hbk_bsl.analysis.diagnostics import DiagnosticEngine

        diags = DiagnosticEngine(select={"BSL131"}).check_file(str(p))
        assert "BSL131" in [d.code for d in diags]

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
        assert diags[0].message == 'Нужно удалить дубли раздела "Тест"'

    def test_duplicate_non_empty_region_not_detected(self, tmp_path: Path) -> None:
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
        assert "BSL131" not in [d.code for d in diags]


# ---------------------------------------------------------------------------
# BSL202 / BSL205 / BSL223 / BSL243 / BSL249
# ---------------------------------------------------------------------------


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

    def test_bsl243_self_insertion_detected(self, tmp_path: Path) -> None:
        diags = _check("Массив.Добавить(Массив);\n", tmp_path, select={"BSL243"})
        assert "BSL243" in _codes(diags)

    def test_bsl249_style_constructor_detected(self, tmp_path: Path) -> None:
        diags = _check("ЦветФона = Новый Цвет(255, 0, 0);\n", tmp_path, select={"BSL249"})
        bsl249 = [d for d in diags if d.code == "BSL249"]
        assert len(bsl249) == 1
        assert bsl249[0].character == 11
        assert bsl249[0].severity is Severity.ERROR
        assert bsl249[0].message == "Замените конструктор Цвет на получение элемента стиля"

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
        assert bsl153[0].message == 'Ключевое слово "ИЗ" написано не канонически'

    def test_bsl221_missing_declared_language_detected(self, tmp_path: Path) -> None:
        diags = _check("Сообщение = НСтр(\"en = 'Done'\");\n", tmp_path, select={"BSL221"})
        assert "BSL221" in _codes(diags)

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

    def test_bsl271_unix_unavailable_object_detected(self, tmp_path: Path) -> None:
        diags = _check(
            'Компонента = Новый COMОбъект("Excel.Application");\n', tmp_path, select={"BSL271"}
        )
        assert "BSL271" in _codes(diags)

    def test_bsl276_proceed_with_call_without_annotation_detected(self, tmp_path: Path) -> None:
        diags = _check(
            "Процедура Тест()\n    ПродолжитьВызов();\nКонецПроцедуры\n",
            tmp_path,
            select={"BSL276"},
        )
        assert "BSL276" in _codes(diags)


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# BSL190 — FormDataToValue
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# BSL255 — TryNumber
# ---------------------------------------------------------------------------


class TestBsl255TryNumber:
    def test_matches_bslls_fixture(self) -> None:
        fixture = (
            Path(".agent/tmp/bslls-source/src/test/resources/diagnostics")
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


class TestBsl257UnaryPlusInConcatenation:
    def test_matches_bslls_fixture(self) -> None:
        fixture = (
            Path(".agent/tmp/bslls-source/src/test/resources/diagnostics")
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


class TestBsl273VirtualTableCallWithoutParameters:
    def test_matches_bslls_fixture(self) -> None:
        fixture = (
            Path(".agent/tmp/bslls-source/src/test/resources/diagnostics")
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


class TestBsl279YoLetterUsage:
    def test_matches_bslls_fixture(self) -> None:
        fixture = (
            Path(".agent/tmp/bslls-source/src/test/resources/diagnostics")
            / "YoLetterUsageDiagnostic.bsl"
        )
        if not fixture.exists():
            pytest.skip("BSLLS fixture is not available")

        diags = [
            d
            for d in DiagnosticEngine(select={"BSL279"}).check_file(str(fixture))
            if d.code == "BSL279"
        ]

        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (1, 6, 1, 11),
            (3, 10, 3, 20),
            (3, 21, 3, 25),
            (4, 13, 4, 17),
            (6, 39, 6, 43),
        ]
        assert {d.severity for d in diags} == {Severity.INFORMATION}
        assert {d.message for d in diags} == {
            'В текстах модулях не допускается использовать букву "Ё".'
        }


class TestBsl277WrongUseOfRollbackTransaction:
    def test_matches_bslls_fixture(self) -> None:
        fixture = (
            Path(".agent/tmp/bslls-source/src/test/resources/diagnostics")
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


class TestBsl276WrongUseFunctionProceedWithCall:
    def test_matches_bslls_fixture(self) -> None:
        fixture = (
            Path(".agent/tmp/bslls-source/src/test/resources/diagnostics")
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


class TestBsl263UseLessForEach:
    def test_matches_bslls_fixture(self) -> None:
        fixture = (
            Path(".agent/tmp/bslls-source/src/test/resources/diagnostics")
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


class TestBsl199IfElseIfEndsWithElse:
    def test_matches_bslls_fixture(self) -> None:
        fixture = (
            Path(".agent/tmp/bslls-source/src/test/resources/diagnostics")
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


class TestBsl198IfElseDuplicatedCondition:
    def test_matches_bslls_fixture(self) -> None:
        fixture = (
            Path(".agent/tmp/bslls-source/src/test/resources/diagnostics")
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


class TestBsl197IfElseDuplicatedCodeBlock:
    def test_matches_bslls_fixture(self) -> None:
        fixture = (
            Path(".agent/tmp/bslls-source/src/test/resources/diagnostics")
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


class TestBsl225NumberOfValuesInStructureConstructorBslls:
    def test_matches_bslls_fixture(self) -> None:
        fixture = (
            Path(".agent/tmp/bslls-source/src/test/resources/diagnostics")
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


class TestBsl262UsageWriteLogEvent:
    def test_matches_bslls_fixture(self) -> None:
        fixture = (
            Path(".agent/tmp/bslls-source/src/test/resources/diagnostics")
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


class TestBsl151BeginTransactionBeforeTryCatch:
    def test_matches_bslls_fixture(self) -> None:
        fixture = (
            Path(".agent/tmp/bslls-source/src/test/resources/diagnostics")
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


class TestBsl157CommitTransactionOutsideTryCatch:
    def test_matches_bslls_fixture(self) -> None:
        fixture = (
            Path(".agent/tmp/bslls-source/src/test/resources/diagnostics")
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

    def test_matches_bslls_single_sub_fixture(self) -> None:
        fixture = (
            Path(".agent/tmp/bslls-source/src/test/resources/diagnostics")
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


class TestBsl230PairingBrokenTransaction:
    def test_matches_bslls_fixture(self) -> None:
        fixture = (
            Path(".agent/tmp/bslls-source/src/test/resources/diagnostics")
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


class TestBsl227OneStatementPerLine:
    def test_matches_bslls_fixture(self) -> None:
        fixture = (
            Path(".agent/tmp/bslls-source/src/test/resources/diagnostics")
            / "OneStatementPerLineDiagnostic.bsl"
        )
        if not fixture.exists():
            pytest.skip("BSLLS fixture is not available")

        diags = [
            diag
            for diag in DiagnosticEngine(select={"BSL227"}).check_file(str(fixture))
            if diag.code == "BSL227"
        ]
        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (4, 8, 4, 14),
            (9, 18, 9, 32),
            (9, 33, 9, 37),
            (13, 5, 13, 9),
            (13, 10, 13, 14),
        ]
        assert {diag.severity for diag in diags} == {Severity.INFORMATION}

    def test_matches_bslls_end_file_fixture(self) -> None:
        fixture = (
            Path(".agent/tmp/bslls-source/src/test/resources/diagnostics")
            / "OneStatementPerLineDiagnosticEndFile.bsl"
        )
        if not fixture.exists():
            pytest.skip("BSLLS fixture is not available")

        diags = [
            diag
            for diag in DiagnosticEngine(select={"BSL227"}).check_file(str(fixture))
            if diag.code == "BSL227"
        ]
        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (2, 5, 2, 9),
            (2, 10, 2, 14),
        ]
        assert {diag.severity for diag in diags} == {Severity.INFORMATION}


class TestBsl149AssignAliasFieldsInQuery:
    def test_matches_bslls_fixture(self) -> None:
        fixture = (
            Path(".agent/tmp/bslls-source/src/test/resources/diagnostics")
            / "AssignAliasFieldsInQueryDiagnostic.bsl"
        )
        if not fixture.exists():
            pytest.skip("BSLLS fixture is not available")

        diags = [
            diag
            for diag in DiagnosticEngine(select={"BSL149"}).check_file(str(fixture))
            if diag.code == "BSL149"
        ]
        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (4, 3, 4, 16),
            (6, 3, 6, 17),
            (22, 3, 22, 16),
            (24, 3, 24, 17),
            (43, 4, 43, 17),
        ]
        assert {diag.severity for diag in diags} == {Severity.WARNING}


class TestBsl186ExtraCommas:
    def test_matches_bslls_fixture(self) -> None:
        fixture = (
            Path(".agent/tmp/bslls-source/src/test/resources/diagnostics")
            / "ExtraCommasDiagnostic.bsl"
        )
        if not fixture.exists():
            pytest.skip("BSLLS fixture is not available")

        diags = [
            diag
            for diag in DiagnosticEngine(select={"BSL186"}).check_file(str(fixture))
            if diag.code == "BSL186"
        ]
        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (9, 35, 9, 36),
            (10, 35, 10, 36),
            (11, 49, 11, 50),
            (12, 45, 12, 46),
            (14, 31, 14, 32),
            (18, 38, 18, 39),
        ]

    def test_string_argument_before_closing_paren_is_not_extra_comma(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                ПараметрыЗаписи.Вставить("Комментарий", "");
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL186"})
        assert [diag for diag in diags if diag.code == "BSL186"] == []


class TestRuleMetadataCompleteness:
    def test_all_rules_in_metadata(self) -> None:
        from onec_hbk_bsl.analysis.diagnostics import _BSLLS_NAME_TO_CODE, RULE_METADATA

        missing = set(_BSLLS_NAME_TO_CODE.values()) - set(RULE_METADATA.keys())
        assert not missing, f"Missing BSLLS RULE_METADATA entries: {missing}"
