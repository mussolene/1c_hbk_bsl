"""Line, text, style, and security diagnostics."""

from __future__ import annotations

import re
import textwrap
from pathlib import Path

import pytest

from onec_hbk_bsl.analysis.diagnostics import (
    DiagnosticEngine,
    Severity,
)
from onec_hbk_bsl.analysis.document_snapshot import build_document_snapshot
from tests.diagnostic_test_support import _check, _codes, _rule_msg

pytestmark = pytest.mark.unit


# BSL180, BSL183, BSL184, BSL185, BSL188, BSL203, BSL226, BSL247, BSL250, BSL264, BSL267, BSL272 — TestSecurityApiParityBatch
class TestSecurityApiParityBatch:
    def test_bsl180_disable_safe_mode(self, tmp_path: Path) -> None:
        content = """\
            Процедура Метод()
                УстановитьБезопасныйРежим(Ложь);
                УстановитьОтключениеБезопасногоРежима(Истина);
                УстановитьБезопасныйРежим(Значение);
                УстановитьОтключениеБезопасногоРежима(Значение);
                УстановитьБезопасныйРежим(Истина);
                УстановитьОтключениеБезопасногоРежима(Ложь);
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL180"}) if d.code == "BSL180"]
        assert [(d.line, d.character, d.end_character) for d in diags] == [
            (2, 4, 29),
            (3, 4, 41),
            (4, 4, 29),
            (5, 4, 41),
        ]

    def test_bsl180_ignores_object_calls_strings_and_comments(self, tmp_path: Path) -> None:
        content = """\
            Процедура Метод()
                Объект.УстановитьБезопасныйРежим(Ложь);
                Текст = "УстановитьОтключениеБезопасногоРежима(Истина)";
                // УстановитьБезопасныйРежим(Ложь);
            КонецПроцедуры
        """
        assert "BSL180" not in _codes(_check(content, tmp_path, select={"BSL180"}))

    def test_bsl188_file_system_access_uses_cst_calls_and_constructors(
        self, tmp_path: Path
    ) -> None:
        content = """\
            Процедура Метод()
                Ф = Новый Файл("a.txt");
                Данные = Новый("ДвоичныеДанные", "a.txt");
                Каталог = КаталогВременныхФайлов();
                КопироватьФайл("a.txt", "b.txt");
                Объект.КаталогВременныхФайлов();
                Текст = "Новый Файл(""a.txt"")";
                // УдалитьФайлы("a.txt");
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL188"}) if d.code == "BSL188"]
        assert [(d.line, d.character, d.severity.name) for d in diags] == [
            (2, 8, "WARNING"),
            (3, 13, "WARNING"),
            (4, 14, "WARNING"),
            (5, 4, "WARNING"),
        ]

    def test_bsl203_internet_access_uses_cst_constructors(self, tmp_path: Path) -> None:
        content = """\
            Процедура Метод()
                Соединение = Новый HTTPСоединение("example.org");
                Запрос = Новый("HTTPЗапрос", "/");
                Текст = "Новый HTTPСоединение(""example.org"")";
                // Новый ИнтернетПрокси;
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL203"}) if d.code == "BSL203"]
        assert [(d.line, d.character, d.severity.name) for d in diags] == [
            (2, 17, "WARNING"),
            (3, 13, "WARNING"),
        ]

    def test_bsl264_system_information_uses_cst_constructors(self, tmp_path: Path) -> None:
        content = """\
            Процедура Метод()
                Инфо = Новый СистемнаяИнформация;
                Info = New("SystemInfo");
                Текст = "Новый СистемнаяИнформация";
                // Новый СистемнаяИнформация;
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL264"}) if d.code == "BSL264"]
        assert [(d.line, d.character, d.severity.name) for d in diags] == [
            (2, 11, "WARNING"),
            (3, 11, "WARNING"),
        ]

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
        assert {d.message for d in diags} == {_rule_msg("BSL183")}

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
        assert {d.message for d in diags} == {_rule_msg("BSL226")}

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
        assert {d.message for d in diags} == {_rule_msg("BSL247")}

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
        assert {d.message for d in diags} == {_rule_msg("BSL250")}

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
        assert {d.message for d in diags} == {_rule_msg("BSL267")}

    @pytest.mark.external_bslls
    def test_bsl272_synchronous_calls_matches_bslls_fixture(self, tmp_path: Path) -> None:
        fixture = (
            Path(__file__).resolve().parents[1]
            / ".tmp/external-fixtures/bsl-language-server/src/test/resources/diagnostics/UsingSynchronousCallsDiagnostic.bsl"
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

    def test_bsl272_skips_split_module_fragment(self, tmp_path: Path) -> None:
        ext_dir = tmp_path / "DataProcessors" / "Тест" / "Ext"
        ext_dir.mkdir(parents=True)
        (ext_dir / "ObjectModule.bsl").write_text("// full module\n", encoding="utf-8")
        path = ext_dir / "УдалитьФайл.bsl"
        path.write_text(
            'Процедура П()\n    УдалитьФайлы("tmp.xml");\nКонецПроцедуры\n',
            encoding="utf-8",
        )

        diags = DiagnosticEngine(select={"BSL272"}).check_file(str(path))

        assert "BSL272" not in _codes(diags)

    def test_bsl272_skips_ext_fragment_without_canonical_module(self, tmp_path: Path) -> None:
        ext_dir = tmp_path / "DataProcessors" / "Тест" / "Ext"
        ext_dir.mkdir(parents=True)
        (ext_dir / "ДругойФрагмент.bsl").write_text("// sibling\n", encoding="utf-8")
        path = ext_dir / "УдалитьФайл.bsl"
        path.write_text(
            'Процедура П()\n    УдалитьФайлы("tmp.xml");\nКонецПроцедуры\n',
            encoding="utf-8",
        )

        diags = DiagnosticEngine(select={"BSL272"}).check_file(str(path))

        assert "BSL272" not in _codes(diags)

    def test_bsl272_skips_split_layout_module(self, tmp_path: Path) -> None:
        form_dir = tmp_path / "Forms" / "Форма" / "Ext" / "Form"
        form_dir.mkdir(parents=True)
        (form_dir / "Module.header").write_text("", encoding="utf-8")
        path = form_dir / "Module.bsl"
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


# BSL171 — TestBsl171CrazyMultilineString
class TestBsl171CrazyMultilineString:
    def test_adjacent_literals_on_same_line_report_full_pair(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Строка = "ВВВ" "СС";
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL171"}) if d.code == "BSL171"]
        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (2, 13, 2, 23),
        ]

    def test_adjacent_literals_on_next_line_report_cross_line_range(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Строка = "ВВВ"
                "СС";
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL171"}) if d.code == "BSL171"]
        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (2, 13, 3, 8),
        ]

    def test_concat_escaped_quotes_and_comments_do_not_report(self, tmp_path: Path) -> None:
        content = '''\
            Процедура Тест()
                Строка = "ВВВ" + "СС";
                Строка = "ВВВ ""СС""";
                // "ВВВ"
                "СС";
            КонецПроцедуры
        '''
        assert "BSL171" not in _codes(_check(content, tmp_path, select={"BSL171"}))


# BSL251 — TestBsl251TernaryOperatorUsage
class TestBsl251TernaryOperatorUsage:
    def test_simple_ternary_is_reported(self, tmp_path: Path) -> None:
        content = "Результат = ?(Условие, 1, 0);\n"
        diags = [d for d in _check(content, tmp_path, select={"BSL251"}) if d.code == "BSL251"]
        assert [
            (d.line, d.character, d.end_line, d.end_character, d.severity.name) for d in diags
        ] == [
            (1, 12, 1, 28, "INFORMATION"),
        ]

    def test_multiline_ternary_uses_full_span(self, tmp_path: Path) -> None:
        content = """\
Результат = ?(Условие,
    Истина,
    Ложь);
"""
        diags = [d for d in _check(content, tmp_path, select={"BSL251"}) if d.code == "BSL251"]
        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (1, 12, 3, 9),
        ]

    def test_strings_and_comments_are_not_reported(self, tmp_path: Path) -> None:
        content = """\
Текст = "?(Условие, 1, 0)";
// Значение = ?(Условие, 1, 0);
"""
        assert "BSL251" not in _codes(_check(content, tmp_path, select={"BSL251"}))


# BSL005 — TestBsl005HardcodeNetworkAddress
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

    def test_ip_address_in_version_function_is_still_detected(self, tmp_path: Path) -> None:
        content = """
            Функция ВерсияСервера()
                Возврат "192.168.1.100";
            КонецФункции
        """
        diags = _check(content, tmp_path)
        assert "BSL005" in _codes(diags)

    def test_ip_shaped_version_literals_are_detected(self, tmp_path: Path) -> None:
        content = """
            Функция ВерсияВнешнейКомпоненты()
                Возврат "5.32.4.635";
            КонецФункции

            Процедура ПроверитьВерсию()
                Результат = (СравнитьВерсии(Версия, "6.0.39.08") >= 0);
                Параметры.Вставить("Версия", "4.1.3.3");
            КонецПроцедуры
        """
        diags = _check(content, tmp_path)
        assert _codes(diags).count("BSL005") == 3

    def test_no_hardcode_no_warning(self, tmp_path: Path) -> None:
        content = "Адрес = ПолучитьАдрес();\n"
        diags = _check(content, tmp_path)
        assert "BSL005" not in _codes(diags)

    def test_in_comment_ignored(self, tmp_path: Path) -> None:
        content = '// Адрес = "http://example.com";\n'
        diags = _check(content, tmp_path)
        assert "BSL005" not in _codes(diags)


# BSL006 — TestBsl006HardcodePath
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


# BSL023 — TestBsl023UsingServiceTag
class TestBsl023UsingServiceTag:
    def test_todo_detected(self, tmp_path: Path) -> None:
        content = "// TODO: реализовать проверку\nПроцедура Тест()\nКонецПроцедуры\n"
        diags = _check(content, tmp_path)
        assert "BSL023" in _codes(diags)

    def test_fixme_detected(self, tmp_path: Path) -> None:
        content = "// FIXME: баг с кодировкой\nА = 1;\n"
        diags = _check(content, tmp_path)
        assert "BSL023" in _codes(diags)

    def test_service_tag_range_starts_at_comment(self, tmp_path: Path) -> None:
        content = "    // FIXME: баг с кодировкой\nА = 1;\n"
        diags = [d for d in _check(content, tmp_path, select={"BSL023"}) if d.code == "BSL023"]

        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (1, 4, 1, len(content.splitlines()[0]))
        ]

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


# BSL024 — TestBsl024SpaceAtStartComment
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

    def test_incomplete_commented_call_reports_bsl024(self, tmp_path: Path) -> None:
        content = "//НСтр(\"ru='строка'\") +\nА = 1;\n"
        diags = _check(content, tmp_path, select={"BSL024"})
        assert "BSL024" in _codes(diags)

    def test_commented_if_without_comparison_reports_bsl024(self, tmp_path: Path) -> None:
        content = "//Если Условие Тогда\n//КонецЕсли;\nА = 1;\n"
        diags = _check(content, tmp_path, select={"BSL024"})
        assert "BSL024" in _codes(diags)

    def test_commented_if_with_call_reports_bsl024(self, tmp_path: Path) -> None:
        content = "//Если ИспользоватьКонтурМаркировку() Тогда\nА = 1;\n"
        diags = _check(content, tmp_path, select={"BSL024"})
        assert "BSL024" in _codes(diags)

    def test_commented_region_start_is_skipped_but_end_reports(self, tmp_path: Path) -> None:
        content = "//#Область СлужебныйИнтерфейс\n//#КонецОбласти\n"
        diags = _check(content, tmp_path, select={"BSL024"})
        assert [(d.line, d.character) for d in diags if d.code == "BSL024"] == [(2, 0)]

    def test_query_pipe_comment_reports_bsl024(self, tmp_path: Path) -> None:
        content = "//|\tИ Поле = &Поле\nА = 1;\n"
        diags = _check(content, tmp_path, select={"BSL024"})
        assert "BSL024" in _codes(diags)

    def test_commented_query_string_open_no_bsl024(self, tmp_path: Path) -> None:
        content = '//"ВЫБРАТЬ РАЗРЕШЕННЫЕ ПЕРВЫЕ 1\nА = 1;\n'
        diags = _check(content, tmp_path, select={"BSL024"})
        assert "BSL024" not in _codes(diags)

    def test_commented_call_close_no_bsl024(self, tmp_path: Path) -> None:
        content = "//);\nА = 1;\n"
        diags = _check(content, tmp_path, select={"BSL024"})
        assert "BSL024" not in _codes(diags)

    def test_inline_comment_without_space_reports(self, tmp_path: Path) -> None:
        content = "Перем1 = 7; //И это плохо\n"
        diags = _check(content, tmp_path, select={"BSL024"})
        bsl024 = [d for d in diags if d.code == "BSL024"]
        assert len(bsl024) == 1
        assert bsl024[0].character == content.index("//")
        assert bsl024[0].message == _rule_msg("BSL024")

    def test_four_slashes_with_text_reports(self, tmp_path: Path) -> None:
        content = "////Текст с ошибкой\n"
        diags = _check(content, tmp_path, select={"BSL024"})
        assert "BSL024" in _codes(diags)

    def test_inline_comment_function_like_text_reports(self, tmp_path: Path) -> None:
        content = "КонецФункции //НоваяТаблицаЗначений()\n"
        diags = _check(content, tmp_path, select={"BSL024"})
        assert "BSL024" in _codes(diags)

    def test_url_string_with_stale_multiline_state_no_bsl024(self, tmp_path: Path) -> None:
        content = 'Ссылка = "https://support.example/path";\n'
        path = tmp_path / "ObjectModule.bsl"
        path.write_text(content, encoding="utf-8")
        snapshot = build_document_snapshot(str(path), content=content)
        snapshot._line_string_states = [True]
        diags = DiagnosticEngine(select={"BSL024"}).check_snapshot(snapshot)
        assert "BSL024" not in _codes(diags)

    def test_comment_text_starting_with_function_word_reports(self, tmp_path: Path) -> None:
        content = "//Функция документа входит в коллекцию\n"
        diags = _check(content, tmp_path, select={"BSL024"})
        assert "BSL024" in _codes(diags)

    def test_commented_return_reports(self, tmp_path: Path) -> None:
        content = "\t//Возврат Истина;\n"
        diags = _check(content, tmp_path, select={"BSL024"})
        assert "BSL024" in _codes(diags)

    def test_string_literal_after_empty_string_is_not_comment(self, tmp_path: Path) -> None:
        content = 'Текст = "Начало\\n|" + ?(Шаблон = "", "\\t//Возврат Истина;", Шаблон) + "";\n'
        diags = _check(content, tmp_path, select={"BSL024"})
        assert "BSL024" not in _codes(diags)


# BSL200 — TestBsl200IncorrectLineBreak
class TestBsl200IncorrectLineBreak:
    def test_line_ending_with_plus_reports(self, tmp_path: Path) -> None:
        content = """\
            Сумма = Часть1 +
                Часть2;
        """
        diags = _check(content, tmp_path, select={"BSL200"})
        bsl200 = [d for d in diags if d.code == "BSL200"]
        assert bsl200
        assert bsl200[0].message == _rule_msg("BSL200")

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

    @pytest.mark.external_bslls
    def test_matches_bslls_fixture(self) -> None:
        fixture = Path(
            ".tmp/external-fixtures/bsl-language-server/src/test/resources/diagnostics/IncorrectLineBreakDiagnostic.bsl"
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


# BSL029 — TestBsl029MagicNumber
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
        assert diag.message == _rule_msg("BSL029")

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

    def test_correspondence_insert_value_in_nested_block_matches_bslls(
        self, tmp_path: Path
    ) -> None:
        content = """\
            Процедура Тест()
                Результат = Новый Соответствие;
                Если Истина Тогда
                    Результат.Вставить("Код", 2);
                КонецЕсли;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL029"})
        assert [(d.line, d.character, d.end_character) for d in diags if d.code == "BSL029"] == [
            (4, 34, 35),
        ]

    def test_nested_constructor_numbers_inside_structure_are_reported(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Параметры = Новый Структура("ЦветФона", Новый Цвет(255, 237, 166));
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL029"})
        assert [(d.line, d.character, d.end_character) for d in diags if d.code == "BSL029"] == [
            (2, 55, 58),
            (2, 60, 63),
            (2, 65, 68),
        ]

    def test_loop_bound_expression_reports_magic_number(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест(МассивРазрядов)
                Для Сч = 1 По 3 - МассивРазрядов.Количество() Цикл
                КонецЦикла;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL029"})
        assert [(d.line, d.character, d.end_character) for d in diags if d.code == "BSL029"] == [
            (2, 18, 19),
        ]

    def test_binary_minus_reports_number_without_sign(self, tmp_path: Path) -> None:
        content = """\
            Функция Тест(Значение)
                Возврат Лев(Значение, СтрДлина(Значение)-2);
            КонецФункции
        """
        diags = _check(content, tmp_path, select={"BSL029"})
        assert [(d.line, d.character, d.end_character) for d in diags if d.code == "BSL029"] == [
            (2, 45, 46),
        ]

    def test_multiline_string_tail_call_argument_is_reported(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Предупреждение("Недостаточная длина
                    |минимум 50 символов", 60);
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL029"})
        assert [(d.line, d.character, d.end_character) for d in diags if d.code == "BSL029"] == [
            (3, 31, 33),
        ]

    def test_query_text_numbers_are_not_reported(self, tmp_path: Path) -> None:
        content = '''\
            Процедура Тест()
                ТекстЗапроса =
                "ВЫБОР
                |КОГДА ВЫРАЗИТЬ(Имя КАК СТРОКА(1000)) <> """" ТОГДА Имя
                |КОНЕЦ";
            КонецПроцедуры
        '''
        diags = _check(content, tmp_path, select={"BSL029"})
        assert "BSL029" not in _codes(diags)

    def test_simple_numeric_assignment_expression_is_not_reported(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Объект[ИмяРеквизита] = 2;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL029"})
        assert "BSL029" not in _codes(diags)

    def test_simple_property_assignment_value_is_not_reported(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Объект.Свойство = 42;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL029"})
        assert "BSL029" not in _codes(diags)

    def test_property_assignment_expression_is_reported(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Объект.Свойство = 40 + 2;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL029"})
        assert [(d.line, d.character, d.end_character) for d in diags if d.code == "BSL029"] == [
            (2, 22, 24),
            (2, 27, 28),
        ]

    def test_property_assignment_call_arguments_are_reported(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Объект.Свойство = ОписаниеТипаЧисло(15, 2);
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL029"})
        assert [(d.line, d.character, d.end_character) for d in diags if d.code == "BSL029"] == [
            (2, 40, 42),
            (2, 44, 45),
        ]

    def test_index_assignment_expression_is_still_reported(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Объект[ИмяРеквизита] = 40 + 2;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL029"})
        assert [(d.line, d.character, d.end_character) for d in diags if d.code == "BSL029"] == [
            (2, 27, 29),
            (2, 32, 33),
        ]

    def test_default_parameter_value_is_not_reported(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест(
                КоличествоПараметров = 2)
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL029"})
        assert "BSL029" not in _codes(diags)

    def test_multiline_string_concat_placeholders_are_not_reported(self, tmp_path: Path) -> None:
        content = '''\
            Процедура Тест()
                Текст = "<p>" + Картинка + "</p>
                    |<p>""" + Значение + """> %3</p>";
            КонецПроцедуры
        '''
        diags = _check(content, tmp_path, select={"BSL029"})
        assert "BSL029" not in _codes(diags)

    def test_known_correspondence_insert_with_mixed_indent_is_skipped(self, tmp_path: Path) -> None:
        content = """\
            Функция Тест()
\t\tРезультат = Новый Соответствие;
    Результат.Вставить("Код", 16);
\t\tВозврат Результат;
            КонецФункции
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

    def test_multiline_nstr_placeholders_are_not_magic_numbers(self, tmp_path: Path) -> None:
        content = """\
            Функция Тест()
                СтрокаФормат = НСтр("ru = '%1, %4 (исполнителем назначен %2) выполнил(а) задачу:
                    |%3'") + Символы.ПС;
                Возврат СтрокаФормат;
            КонецФункции
        """
        diags = _check(content, tmp_path, select={"BSL029"})
        assert "BSL029" not in _codes(diags)

    def test_call_argument_after_parenthesized_expression_is_reported(self, tmp_path: Path) -> None:
        content = """\
            Функция Тест(Сумма, НДС, Количество)
                Возврат Окр((Сумма - НДС) / Количество, 2);
            КонецФункции
        """
        diags = _check(content, tmp_path, select={"BSL029"})
        assert [(d.line, d.character, d.end_character) for d in diags if d.code == "BSL029"] == [
            (2, 44, 45),
        ]

    @pytest.mark.external_bslls
    def test_matches_bslls_fixture(self) -> None:
        fixture = Path(
            ".tmp/external-fixtures/bsl-language-server/src/test/resources/diagnostics/MagicNumberDiagnostic.bsl"
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


# BSL025 — TestBsl025EmptyStatement
class TestBsl025EmptyStatement:
    def test_standalone_semicolon_in_procedure_detected(self, tmp_path: Path) -> None:
        content = "Процедура Тест()\n    ;\nКонецПроцедуры\n"
        diags = _check(content, tmp_path, select={"BSL025"})
        assert [(d.line, d.character, d.end_character) for d in diags if d.code == "BSL025"] == [
            (2, 4, 5)
        ]

    def test_standalone_semicolon_in_module_body_detected(self, tmp_path: Path) -> None:
        content = ";\nА = 1;\n"
        diags = _check(content, tmp_path, select={"BSL025"})
        assert [(d.line, d.character, d.end_character) for d in diags if d.code == "BSL025"] == [
            (1, 0, 1)
        ]

    def test_valid_while_end_semicolon_no_warning(self, tmp_path: Path) -> None:
        content = "Пока Истина Цикл\nКонецЦикла;\n"
        diags = _check(content, tmp_path, select={"BSL025"})
        assert "BSL025" not in _codes(diags)

    def test_method_header_semicolon_is_empty_statement(self, tmp_path: Path) -> None:
        content = "Процедура Тест();\nКонецПроцедуры\n"
        diags = _check(content, tmp_path, select={"BSL025"})
        assert "BSL025" in _codes(diags)

    def test_double_semicolon_reports_second_semicolon(self, tmp_path: Path) -> None:
        content = "А = 1;;\n"
        diags = _check(content, tmp_path, select={"BSL025"})
        assert [(d.line, d.character, d.end_character) for d in diags if d.code == "BSL025"] == [
            (1, 6, 7)
        ]

    def test_standalone_semicolon_in_exception_detected(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Попытка
                    А = 1;
                Исключение
                    ;
                КонецПопытки;
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL025"})
        assert [(d.line, d.character, d.end_character) for d in diags if d.code == "BSL025"] == [
            (5, 8, 9)
        ]


# BSL025, BSL030 — TestBsl030HeaderSemicolon
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

    def test_missing_semicolon_span_matches_bslls_anchor(self, tmp_path: Path) -> None:
        content = (
            "Функция Тест()\n"
            "    Значение = Объект.Реквизит\n"
            "    Возврат СтруктураИнициализации\n"
            "КонецФункции\n"
        )
        diags = [d for d in _check(content, tmp_path, select={"BSL030"}) if d.code == "BSL030"]
        assert [(d.line, d.character, d.end_character) for d in diags] == [
            (2, 22, 30),
            (3, 12, 34),
        ]

    def test_missing_semicolon_after_call_reports_closing_paren(self, tmp_path: Path) -> None:
        content = 'Процедура Тест()\n    Сообщить("missing")\nКонецПроцедуры\n'
        diags = [d for d in _check(content, tmp_path, select={"BSL030"}) if d.code == "BSL030"]
        assert [(d.line, d.character, d.end_character) for d in diags] == [
            (2, 22, 23),
        ]

    def test_multiline_comparison_operator_is_single_statement(self, tmp_path: Path) -> None:
        content = (
            "Функция Тест()\n"
            '    ЕстьТип = Метаданные.ОпределяемыеТипы.Найти("ПрисоединенныйФайл")\n'
            "        <> Неопределено;\n"
            "    Возврат ЕстьТип;\n"
            "КонецФункции\n"
        )
        diags = [d for d in _check(content, tmp_path, select={"BSL030"}) if d.code == "BSL030"]
        assert not diags

    def test_synthetic_semicolon_presence_contract(self) -> None:
        fixture = Path("tests/fixtures/diag_synthetic/bsl030_semicolon_presence.bsl")
        lines = fixture.read_text(encoding="utf-8").splitlines()
        expected: list[int] = []
        for idx, line in enumerate(lines, start=1):
            match = re.search(r"EXPECT:\s*BSL030(?:\s*\+(\d+))?", line)
            if match:
                expected.append(idx + int(match.group(1) or "1"))

        diags = [
            d
            for d in DiagnosticEngine(select={"BSL030"}).check_file(str(fixture))
            if d.code == "BSL030"
        ]
        assert [d.line for d in diags] == expected


# BSL035 — TestBsl035DuplicateStringLiteral
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
        assert bsl035[0].message == _rule_msg("BSL035")

    def test_two_uses_no_warning_with_threshold_3(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                А = "ОченьДлиннаяСтрока";
                Б = "ОченьДлиннаяСтрока";
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, min_duplicate_uses=3)
        assert "BSL035" not in _codes(diags)

    def test_duplicate_only_on_raise_lines_is_reported(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                ВызватьИсключение "ОченьДлиннаяСтрока";
                ВызватьИсключение "ОченьДлиннаяСтрока";
                ВызватьИсключение "ОченьДлиннаяСтрока";
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, min_duplicate_uses=3, select={"BSL035"})
        bsl035 = [d for d in diags if d.code == "BSL035"]
        assert [(d.line, d.character, d.end_character) for d in bsl035] == [(2, 22, 42)]

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
        assert bsl035[0].message == _rule_msg("BSL035")

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
        assert bsl035[0].message == _rule_msg("BSL035")


# BSL153 — TestBsl153FormModuleParity
class TestBsl153FormModuleParity:
    def test_form_module_path_reports_bsl153(self, tmp_path: Path) -> None:
        """BSLLS parity: form modules are checked for canonical keyword spelling (BSL153)."""
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
        assert "BSL153" in _codes(diags)


# BSL055 — TestBsl055ConsecutiveBlankLines
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

    def test_trailing_blank_run_extends_past_last_line(self, tmp_path: Path) -> None:
        content = "А = 1;\n\n\n"
        bsl_file = tmp_path / "test.bsl"
        bsl_file.write_text(content, encoding="utf-8")
        diags = [
            d
            for d in DiagnosticEngine(select={"BSL055"}).check_file(str(bsl_file))
            if d.code == "BSL055"
        ]
        assert len(diags) == 1
        assert diags[0].line == 2
        assert diags[0].end_line == 4


# BSL149 — TestBsl149AssignAliasFieldsInQueryFixture
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
        assert bsl149[0].end_character > bsl149[0].character
        assert bsl149[0].severity is Severity.WARNING
        assert bsl149[0].message == _rule_msg("BSL149")

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

    def test_case_continuation_without_alias_detected(self, tmp_path: Path) -> None:
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
        assert "BSL149" in _codes(diags)

    def test_plain_string_starting_with_select_word_no_warning(self, tmp_path: Path) -> None:
        content = 'А = "Выбрать тариф";\n'
        diags = _check(content, tmp_path, select={"BSL149"})
        assert "BSL149" not in _codes(diags)

    def test_escaped_query_string_literal_is_not_treated_as_select_field(
        self, tmp_path: Path
    ) -> None:
        content = """\
            ТекстЗапроса = "ВЫБРАТЬ
            |   ""Товар"" КАК ТипНоменклатуры,
            |   Т.Ссылка КАК Ссылка
            |ИЗ
            |   Справочник.Номенклатура КАК Т";
        """
        diags = _check(content, tmp_path, select={"BSL149"})
        assert "BSL149" not in _codes(diags)

    def test_dynamic_union_fragment_no_warning(self, tmp_path: Path) -> None:
        content = """\
            ТекстЗапроса = ТекстЗапроса + "
            |ОБЪЕДИНИТЬ ВСЕ
            |ВЫБРАТЬ
            |   2,
            |   Т.Ссылка
            |ИЗ
            |   Справочник.Тест КАК Т";
        """
        diags = _check(content, tmp_path, select={"BSL149"})
        assert "BSL149" not in _codes(diags)

    def test_dynamic_union_fragment_with_next_query_reports_first_select(
        self, tmp_path: Path
    ) -> None:
        content = """\
            ТекстЗапроса = ТекстЗапроса + "
            |ОБЪЕДИНИТЬ
            |ВЫБРАТЬ
            |   Т.Документ,
            |   Т.ДокументОснование
            |ИЗ
            |   Справочник.Тест КАК Т
            |;
            |ВЫБРАТЬ
            |   Т.Ссылка КАК Ссылка
            |ИЗ
            |   Справочник.Тест КАК Т";
        """
        diags = _check(content, tmp_path, select={"BSL149"})
        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (4, 4, 4, 14),
            (5, 4, 5, 23),
        ]

    def test_dynamic_condition_fragment_no_warning(self, tmp_path: Path) -> None:
        content = """\
            ТекстЗапроса = ТекстЗапроса + "
            |И Т.ПометкаУдаления = ЛОЖЬ
            |ВЫБРАТЬ
            |   Т.Ссылка
            |ИЗ
            |   Справочник.Тест КАК Т";
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

    def test_dynamic_query_tail_is_not_treated_as_complete_query(self, tmp_path: Path) -> None:
        content = """\
            ТекстЗапроса = "ВЫБРАТЬ
            |   Т.Дата,
            |   Т.Ссылка
            |ИЗ
            |   Документ.РасходнаяНакладная КАК Т
            |ГДЕ "
            + ?(ИспользоватьОтбор, "Т.Проведен", "НЕ Т.Проведен");
        """
        diags = _check(content, tmp_path, select={"BSL149"})
        assert "BSL149" not in _codes(diags)

    def test_multiline_expression_alias_after_operator_continuation(self, tmp_path: Path) -> None:
        content = """\
            ТекстЗапроса = "ВЫБРАТЬ
            |   ПОДСТРОКА(Т.Версия, 7, 4)
            |   + ПОДСТРОКА(Т.Версия, 4, 2)
            |   + ПОДСТРОКА(Т.Версия, 1, 2) КАК ВерсияСортировка
            |ИЗ
            |   Справочник.Шаблоны КАК Т";
        """
        diags = _check(content, tmp_path, select={"BSL149"})
        assert "BSL149" not in _codes(diags)


# BSL279 — TestBsl279YoLetterUsage
class TestBsl279YoLetterUsage:
    def test_reports_yo_letter_in_identifier(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Счётчик = 1;
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL279"}) if d.code == "BSL279"]

        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (2, 4, 2, 11)
        ]

    def test_skips_yo_letter_in_comments_and_strings(self, tmp_path: Path) -> None:
        content = """\
            // Счётчик
            Процедура Тест()
                Текст = "Счётчик";
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL279"})

        assert "BSL279" not in _codes(diags)

    @pytest.mark.external_bslls
    def test_matches_bslls_fixture(self) -> None:
        fixture = (
            Path(".tmp/external-fixtures/bsl-language-server/src/test/resources/diagnostics")
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


# BSL227 — TestBsl227OneStatementPerLine
class TestBsl227OneStatementPerLine:
    def test_second_statement_reports_exact_range(self, tmp_path: Path) -> None:
        content = "Процедура Тест()\n    А = 1; Б = 2;\nКонецПроцедуры\n"

        diags = [d for d in _check(content, tmp_path, select={"BSL227"}) if d.code == "BSL227"]

        assert [
            (d.line, d.character, d.end_line, d.end_character, d.severity, d.message) for d in diags
        ] == [(2, 11, 2, 17, Severity.INFORMATION, _rule_msg("BSL227"))]

    def test_one_statement_per_line_is_clean(self, tmp_path: Path) -> None:
        content = "Процедура Тест()\n    А = 1;\n    Б = 2;\nКонецПроцедуры\n"

        assert "BSL227" not in _codes(_check(content, tmp_path, select={"BSL227"}))

    @pytest.mark.external_bslls
    def test_matches_bslls_fixture(self) -> None:
        fixture = (
            Path(".tmp/external-fixtures/bsl-language-server/src/test/resources/diagnostics")
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

    @pytest.mark.external_bslls
    def test_matches_bslls_end_file_fixture(self) -> None:
        fixture = (
            Path(".tmp/external-fixtures/bsl-language-server/src/test/resources/diagnostics")
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


# BSL149 — TestBsl149AssignAliasFieldsInQuery
class TestBsl149AssignAliasFieldsInQuery:
    @pytest.mark.external_bslls
    def test_matches_bslls_fixture(self) -> None:
        fixture = (
            Path(".tmp/external-fixtures/bsl-language-server/src/test/resources/diagnostics")
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


# BSL186 — TestBsl186ExtraCommas
class TestBsl186ExtraCommas:
    @pytest.mark.external_bslls
    def test_matches_bslls_fixture(self) -> None:
        fixture = (
            Path(".tmp/external-fixtures/bsl-language-server/src/test/resources/diagnostics")
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

    def test_multiline_trailing_comma_skips_comments_and_blank_lines(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Метод(
                    Параметр,
                    // пояснение

                );
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL186"})
        assert [(diag.line, diag.character, diag.end_character) for diag in diags] == [(3, 16, 17)]
