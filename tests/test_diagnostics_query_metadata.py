"""Query text and metadata diagnostics."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from onec_hbk_bsl.analysis import document_snapshot as _document_snapshot
from onec_hbk_bsl.analysis.diagnostics import (
    DiagnosticEngine,
    Severity,
)
from tests.diagnostic_test_support import _check, _codes, _rule_msg

pytestmark = pytest.mark.integration

_SDBL_AVAILABLE = _document_snapshot._SDBL_LANGUAGE is not None
_requires_sdbl = pytest.mark.skipif(
    not _SDBL_AVAILABLE,
    reason="SDBL tree-sitter parser is required",
)


# BSL077, BSL169, BSL170, BSL174, BSL181, BSL182, BSL187, BSL189, BSL191, BSL196, BSL211, BSL213, BSL214, BSL231, BSL232, BSL236, BSL238, BSL241, BSL242, BSL244, BSL246, BSL253, BSL260, BSL261, BSL274 — TestTailParityBatches
class TestTailParityBatches:
    def test_bsl181_duplicate_insert_add_and_expression(self, tmp_path: Path) -> None:
        content = """\
            Процедура Обработчик()
                Коллекция.Вставить("Ключ");
                Коллекция.Вставить("Ключ");
                Массив.Добавить("Значение");
                Массив.Добавить("Значение");
                Карта.Вставить(Префикс + ".Поле", Значение1);
                Карта.Вставить(Префикс + ".Поле", Значение2);
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL181"}) if d.code == "BSL181"]
        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (3, 4, 3, 30),
            (5, 4, 5, 31),
            (7, 4, 7, 48),
        ]

    def test_bsl181_reassignment_resets_collection_facts(self, tmp_path: Path) -> None:
        content = """\
            Процедура Обработчик()
                Условие = Новый Структура;
                Условие.Вставить("ИмяПоля", "Номер");
                Условие = Новый Структура;
                Условие.Вставить("ИмяПоля", "Серия");
            КонецПроцедуры
        """
        assert "BSL181" not in _codes(_check(content, tmp_path, select={"BSL181"}))

    def test_compilation_and_name_tail_pool(self, tmp_path: Path) -> None:
        form_path = (
            tmp_path / "Catalogs" / "Тест" / "Forms" / "Форма" / "Ext" / "Form" / "Module.bsl"
        )
        form_path.parent.mkdir(parents=True)
        form_path.write_text(
            textwrap.dedent(
                """\
                Процедура ПроверитьБит()
                КонецПроцедуры

                Процедура Обработчик()
                    Если Параметры.Свойство("АвтоТест") Тогда
                        Возврат;
                    КонецЕсли;
                    Коллекция.Вставить("Ключ");
                    Коллекция.Вставить("Ключ");
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
        assert next(diag for diag in diags if diag.code == "BSL169").severity is Severity.ERROR

    def test_bsl196_global_context_method_collision_isolated(self, tmp_path: Path) -> None:
        path = tmp_path / "ObjectModule.bsl"
        path.write_text(
            textwrap.dedent(
                """\
                Процедура ПроверитьБит()
                КонецПроцедуры
                """
            ),
            encoding="utf-8",
        )

        bsl196 = [
            d
            for d in DiagnosticEngine(select={"BSL196"}).check_file(str(path))
            if d.code == "BSL196"
        ]
        assert [(d.line, d.character, d.end_character) for d in bsl196] == [(1, 10, 22)]
        assert {d.severity for d in bsl196} == {Severity.ERROR}

    def test_compilation_directive_lost_skips_ordinary_form(self, tmp_path: Path) -> None:
        path = tmp_path / "Catalogs" / "Тест" / "Forms" / "Форма" / "Ext" / "Form" / "Module.bsl"
        xml_path = tmp_path / "Catalogs" / "Тест" / "Forms" / "Форма" / "Ext" / "Form.xml"
        path.parent.mkdir(parents=True)
        xml_path.write_text(
            "<Form><Properties><FormType>Ordinary</FormType></Properties></Form>",
            encoding="utf-8",
        )
        path.write_text(
            textwrap.dedent(
                """\
                Процедура Обработчик()
                КонецПроцедуры
                """
            ),
            encoding="utf-8",
        )

        diags = DiagnosticEngine(select={"BSL169"}).check_file(str(path))

        assert "BSL169" not in _codes(diags)

    def test_compilation_directive_lost_reports_managed_form(self, tmp_path: Path) -> None:
        path = tmp_path / "Catalogs" / "Тест" / "Forms" / "Форма" / "Ext" / "Form" / "Module.bsl"
        xml_path = tmp_path / "Catalogs" / "Тест" / "Forms" / "Форма" / "Ext" / "Form.xml"
        path.parent.mkdir(parents=True)
        xml_path.write_text(
            "<Form><Properties><FormType>Managed</FormType></Properties></Form>",
            encoding="utf-8",
        )
        path.write_text(
            textwrap.dedent(
                """\
                Процедура Обработчик()
                КонецПроцедуры
                """
            ),
            encoding="utf-8",
        )

        diags = DiagnosticEngine(select={"BSL169"}).check_file(str(path))

        assert "BSL169" in _codes(diags)

    def test_compilation_directive_lost_skips_split_form_layout(self, tmp_path: Path) -> None:
        path = tmp_path / "Catalogs" / "Тест" / "Forms" / "Форма" / "Ext" / "Form" / "Module.bsl"
        xml_path = tmp_path / "Catalogs" / "Тест" / "Forms" / "Форма" / "Ext" / "Form.xml"
        path.parent.mkdir(parents=True)
        xml_path.write_text(
            "<Form><Properties><FormType>Managed</FormType></Properties></Form>",
            encoding="utf-8",
        )
        (path.parent / "Module.header").write_text("", encoding="utf-8")
        path.write_text(
            textwrap.dedent(
                """\
                Процедура Обработчик()
                КонецПроцедуры
                """
            ),
            encoding="utf-8",
        )

        diags = DiagnosticEngine(select={"BSL169"}).check_file(str(path))

        assert "BSL169" not in _codes(diags)

    def test_compilation_directive_lost_skips_ordinary_ext_module_without_xml(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "Catalogs" / "Тест" / "Forms" / "Форма" / "Ext" / "Module.bsl"
        path.parent.mkdir(parents=True)
        path.write_text(
            textwrap.dedent(
                """\
                Процедура ПриОткрытии()
                КонецПроцедуры
                """
            ),
            encoding="utf-8",
        )

        diags = DiagnosticEngine(select={"BSL169"}).check_file(str(path))

        assert "BSL169" not in _codes(diags)

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

    def test_needless_compilation_directive_skips_split_form_fragment(self, tmp_path: Path) -> None:
        form_dir = tmp_path / "DataProcessors" / "Тест" / "Forms" / "Форма" / "Ext" / "Form"
        form_dir.mkdir(parents=True)
        (form_dir / "Module.bsl").write_text("// full module\n", encoding="utf-8")
        path = form_dir / "СерверныйМетод.bsl"
        path.write_text(
            textwrap.dedent(
                """\
                &НаСервере
                Процедура СерверныйМетод()
                КонецПроцедуры
                """
            ),
            encoding="utf-8",
        )
        diags = DiagnosticEngine(select={"BSL170"}).check_file(str(path))
        assert "BSL170" not in _codes(diags)

    def test_needless_compilation_directive_skips_split_object_fragment(
        self, tmp_path: Path
    ) -> None:
        ext_dir = tmp_path / "DataProcessors" / "Тест" / "Ext"
        ext_dir.mkdir(parents=True)
        (ext_dir / "ObjectModule.bsl").write_text("// full module\n", encoding="utf-8")
        path = ext_dir / "СерверныйМетод.bsl"
        path.write_text(
            textwrap.dedent(
                """\
                &НаСервере
                Процедура СерверныйМетод()
                КонецПроцедуры
                """
            ),
            encoding="utf-8",
        )
        diags = DiagnosticEngine(select={"BSL170"}).check_file(str(path))
        assert "BSL170" not in _codes(diags)

    def test_unsafe_find_by_code_tail_rule(self, tmp_path: Path) -> None:
        root = tmp_path / "Config"
        root.mkdir(parents=True)
        (root / "Configuration.xml").write_text("<Configuration/>", encoding="utf-8")
        (root / "Catalogs").mkdir()
        (root / "Catalogs" / "Номенклатура.xml").write_text(
            textwrap.dedent(
                """\
                <MetaDataObject>
                    <Catalog>
                        <Properties>
                            <Name>Номенклатура</Name>
                            <CodeSeries>WithinOwner</CodeSeries>
                            <CheckUnique>true</CheckUnique>
                        </Properties>
                    </Catalog>
                </MetaDataObject>
                """
            ),
            encoding="utf-8",
        )
        path = root / "Catalogs" / "Номенклатура" / "Ext" / "ManagerModule.bsl"
        path.parent.mkdir(parents=True)
        path.write_text(
            textwrap.dedent(
                """\
                Процедура Метод()
                    Найденный = Справочники.Номенклатура.НайтиПоКоду("001");
                КонецПроцедуры
                """
            ),
            encoding="utf-8",
        )
        diags = DiagnosticEngine(select={"BSL260"}).check_file(str(path))
        assert "BSL260" in _codes(diags)

    def test_unsafe_find_by_code_uses_metadata_safety(self, tmp_path: Path) -> None:
        root = tmp_path / "Config"
        root.mkdir(parents=True)
        (root / "Configuration.xml").write_text("<Configuration/>", encoding="utf-8")
        (root / "Catalogs").mkdir()
        (root / "Catalogs" / "Номенклатура.xml").write_text(
            textwrap.dedent(
                """\
                <MetaDataObject>
                    <Catalog>
                        <Properties>
                            <Name>Номенклатура</Name>
                            <CodeSeries>WholeCatalog</CodeSeries>
                            <CheckUnique>true</CheckUnique>
                        </Properties>
                    </Catalog>
                </MetaDataObject>
                """
            ),
            encoding="utf-8",
        )
        path = root / "Catalogs" / "Номенклатура" / "Ext" / "ManagerModule.bsl"
        path.parent.mkdir(parents=True)
        path.write_text(
            textwrap.dedent(
                """\
                Процедура Метод()
                    Найденный = Справочники.Номенклатура.НайтиПоКоду("001");
                    Другой = Каталог.НайтиПоКоду("001");
                КонецПроцедуры
                """
            ),
            encoding="utf-8",
        )

        diags = DiagnosticEngine(select={"BSL260"}).check_file(str(path))

        assert "BSL260" not in _codes(diags)

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
        manager_module = obj_dir / "Ext" / "ManagerModule.bsl"
        manager_module.parent.mkdir(parents=True, exist_ok=True)
        manager_module.write_text(
            "Процедура Метод()\nКонецПроцедуры\n",
            encoding="utf-8",
        )
        record_set_module = obj_dir / "Ext" / "RecordSetModule.bsl"
        record_set_module.write_text(
            "Процедура Метод()\nКонецПроцедуры\n",
            encoding="utf-8",
        )
        diags_form = DiagnosticEngine(select={"BSL174", "BSL211", "BSL241", "BSL274"}).check_file(
            str(module_path)
        )
        assert {"BSL211", "BSL241", "BSL274"} <= set(_codes(diags_form))
        assert "BSL174" not in _codes(diags_form)
        diags_manager = DiagnosticEngine(select={"BSL174"}).check_file(str(manager_module))
        assert "BSL174" in _codes(diags_manager)
        manager_diag = next(diag for diag in diags_manager if diag.code == "BSL174")
        assert (
            manager_diag.line,
            manager_diag.character,
            manager_diag.end_line,
            manager_diag.end_character,
        ) == (
            1,
            0,
            1,
            9,
        )
        diags_record_set = DiagnosticEngine(select={"BSL174"}).check_file(str(record_set_module))
        assert "BSL174" not in _codes(diags_record_set)
        diags_app = DiagnosticEngine(select={"BSL246"}).check_file(str(app_module))
        assert "BSL246" in _codes(diags_app)

    def test_bsl274_reports_form_module_wrong_data_path(self, tmp_path: Path) -> None:
        root = tmp_path / "Config"
        root.mkdir(parents=True)
        (root / "Configuration.xml").write_text("<Configuration/>", encoding="utf-8")
        form_ext = root / "Catalogs" / "CatalogA" / "Forms" / "FormA" / "Ext"
        form_ext.mkdir(parents=True)
        (root / "Catalogs" / "CatalogA.xml").write_text(
            "<MetaDataObject><Catalog><Properties><Name>CatalogA</Name></Properties></Catalog></MetaDataObject>",
            encoding="utf-8",
        )
        (form_ext / "Form.xml").write_text(
            "<Form><Items><Item><DataPath>~Object.Description</DataPath></Item></Items></Form>",
            encoding="utf-8",
        )
        module = form_ext / "Module.bsl"
        module.write_text("Процедура Метод()\nКонецПроцедуры\n", encoding="utf-8")

        diags = [
            d
            for d in DiagnosticEngine(select={"BSL274"}).check_file(str(module))
            if d.code == "BSL274"
        ]

        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (1, 0, 1, 17),
        ]
        assert diags[0].severity is Severity.ERROR

    def test_bsl274_skips_valid_data_path_and_non_form_module(self, tmp_path: Path) -> None:
        root = tmp_path / "Config"
        root.mkdir(parents=True)
        (root / "Configuration.xml").write_text("<Configuration/>", encoding="utf-8")
        form_ext = root / "Catalogs" / "CatalogA" / "Forms" / "FormA" / "Ext"
        form_ext.mkdir(parents=True)
        (root / "Catalogs" / "CatalogA.xml").write_text(
            "<MetaDataObject><Catalog><Properties><Name>CatalogA</Name></Properties></Catalog></MetaDataObject>",
            encoding="utf-8",
        )
        (form_ext / "Form.xml").write_text(
            "<Form><Items><Item><DataPath>Object.Description</DataPath></Item></Items></Form>",
            encoding="utf-8",
        )
        form_module = form_ext / "Module.bsl"
        form_module.write_text("Процедура Метод()\nКонецПроцедуры\n", encoding="utf-8")
        manager_module = root / "Catalogs" / "CatalogA" / "Ext" / "ManagerModule.bsl"
        manager_module.parent.mkdir(parents=True)
        manager_module.write_text("Процедура Метод()\nКонецПроцедуры\n", encoding="utf-8")

        assert "BSL274" not in _codes(
            DiagnosticEngine(select={"BSL274"}).check_file(str(form_module))
        )
        assert "BSL274" not in _codes(
            DiagnosticEngine(select={"BSL274"}).check_file(str(manager_module))
        )

    def test_bsl274_reports_managed_application_module_for_form_without_module(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path / "Config"
        root.mkdir(parents=True)
        (root / "Configuration.xml").write_text("<Configuration/>", encoding="utf-8")
        with_module_ext = root / "Catalogs" / "CatalogA" / "Forms" / "WithModule" / "Ext"
        without_module_ext = root / "Catalogs" / "CatalogA" / "Forms" / "WithoutModule" / "Ext"
        with_module_ext.mkdir(parents=True)
        without_module_ext.mkdir(parents=True)
        (root / "Catalogs" / "CatalogA.xml").write_text(
            "<MetaDataObject><Catalog><Properties><Name>CatalogA</Name></Properties></Catalog></MetaDataObject>",
            encoding="utf-8",
        )
        for form_ext in (with_module_ext, without_module_ext):
            (form_ext / "Form.xml").write_text(
                "<Form><Items><Item><DataPath>~Object.Description</DataPath></Item></Items></Form>",
                encoding="utf-8",
            )
        (with_module_ext / "Module.bsl").write_text(
            "Процедура Метод()\nКонецПроцедуры\n",
            encoding="utf-8",
        )
        app_module = root / "Ext" / "ManagedApplicationModule.bsl"
        app_module.parent.mkdir(parents=True)
        app_module.write_text(
            "Процедура ПриНачалеРаботыСистемы()\nКонецПроцедуры\n",
            encoding="utf-8",
        )

        diags = [
            d
            for d in DiagnosticEngine(select={"BSL274"}).check_file(str(app_module))
            if d.code == "BSL274"
        ]

        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (1, 0, 1, 34),
        ]

    def test_metadata_object_name_length_uses_strict_80_character_threshold(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path / "Config"
        root.mkdir(parents=True)
        (root / "Configuration.xml").write_text("<Configuration/>", encoding="utf-8")

        long_name = "X" * 81
        long_dir = root / "Catalogs" / long_name / "Ext"
        long_dir.mkdir(parents=True)
        (root / "Catalogs" / f"{long_name}.xml").write_text(
            f"<MetaDataObject><Catalog><Properties><Name>{long_name}</Name></Properties></Catalog></MetaDataObject>",
            encoding="utf-8",
        )
        long_module = long_dir / "ManagerModule.bsl"
        long_module.write_text("Процедура Метод()\nКонецПроцедуры\n", encoding="utf-8")

        exact_name = "Y" * 80
        exact_dir = root / "Catalogs" / exact_name / "Ext"
        exact_dir.mkdir(parents=True)
        (root / "Catalogs" / f"{exact_name}.xml").write_text(
            f"<MetaDataObject><Catalog><Properties><Name>{exact_name}</Name></Properties></Catalog></MetaDataObject>",
            encoding="utf-8",
        )
        exact_module = exact_dir / "ManagerModule.bsl"
        exact_module.write_text("Процедура Метод()\nКонецПроцедуры\n", encoding="utf-8")

        long_diags = [
            diag
            for diag in DiagnosticEngine(select={"BSL211"}).check_file(str(long_module))
            if diag.code == "BSL211"
        ]
        assert len(long_diags) == 1
        assert (
            long_diags[0].line,
            long_diags[0].character,
            long_diags[0].end_line,
            long_diags[0].end_character,
        ) == (1, 0, 1, 9)
        assert "BSL211" not in _codes(
            DiagnosticEngine(select={"BSL211"}).check_file(str(exact_module))
        )

    def test_metadata_object_name_length_ignores_long_child_names(self, tmp_path: Path) -> None:
        root = tmp_path / "Config"
        root.mkdir(parents=True)
        (root / "Configuration.xml").write_text("<Configuration/>", encoding="utf-8")

        object_name = "ShortObject"
        obj_dir = root / "Catalogs" / object_name / "Ext"
        obj_dir.mkdir(parents=True)
        (root / "Catalogs" / f"{object_name}.xml").write_text(
            textwrap.dedent(
                f"""\
                <MetaDataObject>
                    <Catalog>
                        <Properties><Name>{object_name}</Name></Properties>
                        <ChildObjects>
                            <Attribute><Properties><Name>{"Z" * 81}</Name></Properties></Attribute>
                        </ChildObjects>
                    </Catalog>
                </MetaDataObject>
                """
            ),
            encoding="utf-8",
        )
        module = obj_dir / "ManagerModule.bsl"
        module.write_text("Процедура Метод()\nКонецПроцедуры\n", encoding="utf-8")

        assert "BSL211" not in _codes(DiagnosticEngine(select={"BSL211"}).check_file(str(module)))

    def test_bsl241_reports_object_child_name_equal_to_owner(self, tmp_path: Path) -> None:
        root = tmp_path / "Config"
        root.mkdir(parents=True)
        (root / "Configuration.xml").write_text("<Configuration/>", encoding="utf-8")

        object_name = "ТестовыйОбъект"
        obj_dir = root / "Catalogs" / object_name / "Ext"
        obj_dir.mkdir(parents=True)
        (root / "Catalogs" / f"{object_name}.xml").write_text(
            textwrap.dedent(
                f"""\
                <MetaDataObject>
                    <Catalog>
                        <Properties><Name>{object_name}</Name></Properties>
                        <ChildObjects>
                            <Attribute><Properties><Name>{object_name}</Name></Properties></Attribute>
                        </ChildObjects>
                    </Catalog>
                </MetaDataObject>
                """
            ),
            encoding="utf-8",
        )
        module = obj_dir / "ManagerModule.bsl"
        module.write_text("Процедура Метод()\nКонецПроцедуры\n", encoding="utf-8")

        diags = [
            diag
            for diag in DiagnosticEngine(select={"BSL241"}).check_file(str(module))
            if diag.code == "BSL241"
        ]
        assert len(diags) == 1
        assert diags[0].severity is Severity.ERROR
        assert (diags[0].line, diags[0].character, diags[0].end_line, diags[0].end_character) == (
            1,
            0,
            1,
            17,
        )

    def test_bsl241_reports_tabular_section_attribute_equal_to_section(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path / "Config"
        root.mkdir(parents=True)
        (root / "Configuration.xml").write_text("<Configuration/>", encoding="utf-8")

        object_name = "ДокументТест"
        section_name = "Строки"
        obj_dir = root / "Documents" / object_name / "Ext"
        obj_dir.mkdir(parents=True)
        (root / "Documents" / f"{object_name}.xml").write_text(
            textwrap.dedent(
                f"""\
                <MetaDataObject>
                    <Document>
                        <Properties><Name>{object_name}</Name></Properties>
                        <ChildObjects>
                            <TabularSection>
                                <Properties><Name>{section_name}</Name></Properties>
                                <ChildObjects>
                                    <Attribute>
                                        <Properties><Name>{section_name}</Name></Properties>
                                    </Attribute>
                                </ChildObjects>
                            </TabularSection>
                        </ChildObjects>
                    </Document>
                </MetaDataObject>
                """
            ),
            encoding="utf-8",
        )
        module = obj_dir / "ObjectModule.bsl"
        module.write_text("Процедура Метод()\nКонецПроцедуры\n", encoding="utf-8")

        diags = [
            diag
            for diag in DiagnosticEngine(select={"BSL241"}).check_file(str(module))
            if diag.code == "BSL241"
        ]
        assert len(diags) == 1
        assert diags[0].severity is Severity.ERROR

    def test_bsl241_skips_near_miss_and_form_only_child_names(self, tmp_path: Path) -> None:
        root = tmp_path / "Config"
        root.mkdir(parents=True)
        (root / "Configuration.xml").write_text("<Configuration/>", encoding="utf-8")

        object_name = "Склад"
        obj_dir = root / "Catalogs" / object_name / "Forms" / "Форма" / "Ext"
        obj_dir.mkdir(parents=True)
        (root / "Catalogs" / f"{object_name}.xml").write_text(
            textwrap.dedent(
                f"""\
                <MetaDataObject>
                    <Catalog>
                        <Properties><Name>{object_name}</Name></Properties>
                        <ChildObjects>
                            <Attribute><Properties><Name>{object_name}Основной</Name></Properties></Attribute>
                            <TabularSection>
                                <Properties><Name>Товары</Name></Properties>
                                <ChildObjects>
                                    <Attribute>
                                        <Properties><Name>Номенклатура</Name></Properties>
                                    </Attribute>
                                </ChildObjects>
                            </TabularSection>
                        </ChildObjects>
                    </Catalog>
                </MetaDataObject>
                """
            ),
            encoding="utf-8",
        )
        (root / "Catalogs" / object_name / "Forms" / "Форма" / "Ext" / "Form.xml").write_text(
            f'<Form><Attributes><Attribute name="{object_name}"/></Attributes></Form>',
            encoding="utf-8",
        )
        module = obj_dir / "Module.bsl"
        module.write_text("Процедура Метод()\nКонецПроцедуры\n", encoding="utf-8")

        assert "BSL241" not in _codes(DiagnosticEngine(select={"BSL241"}).check_file(str(module)))

    def test_bsl241_uses_current_object_without_full_crawl(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = tmp_path / "Config"
        root.mkdir(parents=True)
        (root / "Configuration.xml").write_text("<Configuration/>", encoding="utf-8")

        object_name = "ТестовыйОбъект"
        obj_dir = root / "Catalogs" / object_name / "Ext"
        obj_dir.mkdir(parents=True)
        (root / "Catalogs" / f"{object_name}.xml").write_text(
            textwrap.dedent(
                f"""\
                <MetaDataObject>
                    <Catalog>
                        <Properties><Name>{object_name}</Name></Properties>
                        <ChildObjects>
                            <Attribute><Properties><Name>{object_name}</Name></Properties></Attribute>
                        </ChildObjects>
                    </Catalog>
                </MetaDataObject>
                """
            ),
            encoding="utf-8",
        )
        module = obj_dir / "ManagerModule.bsl"
        module.write_text("Процедура Метод()\nКонецПроцедуры\n", encoding="utf-8")
        monkeypatch.setattr(
            "onec_hbk_bsl.analysis.diagnostics._crawl_config_cached",
            lambda *_args, **_kwargs: pytest.fail("full crawl is not expected for BSL241"),
        )

        assert "BSL241" in _codes(DiagnosticEngine(select={"BSL241"}).check_file(str(module)))

    def test_deny_incomplete_values_skips_non_register_metadata(self, tmp_path: Path) -> None:
        root = tmp_path / "Config"
        root.mkdir(parents=True)
        (root / "Configuration.xml").write_text("<Configuration/>", encoding="utf-8")
        obj_dir = root / "Catalogs" / "Номенклатура"
        (obj_dir / "Ext").mkdir(parents=True)
        (root / "Catalogs" / "Номенклатура.xml").write_text(
            textwrap.dedent(
                """\
                <MetaDataObject>
                    <Catalog>
                        <ChildObjects>
                            <Dimension>
                                <Properties>
                                    <Name>Измерение</Name>
                                    <DenyIncompleteValues>false</DenyIncompleteValues>
                                </Properties>
                            </Dimension>
                        </ChildObjects>
                    </Catalog>
                </MetaDataObject>
                """
            ),
            encoding="utf-8",
        )
        module = obj_dir / "Ext" / "ManagerModule.bsl"
        module.write_text("Процедура Метод()\nКонецПроцедуры\n", encoding="utf-8")

        diags = DiagnosticEngine(select={"BSL174"}).check_file(str(module))

        assert "BSL174" not in _codes(diags)

    def test_bsl189_reports_storage_attribute_but_skips_tabular_section_attribute(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path / "Config"
        root.mkdir(parents=True)
        (root / "Configuration.xml").write_text("<Configuration/>", encoding="utf-8")
        obj_dir = root / "DataProcessors" / "Обработка" / "Ext"
        obj_dir.mkdir(parents=True)
        (root / "DataProcessors" / "Обработка.xml").write_text(
            textwrap.dedent(
                """\
                <MetaDataObject>
                    <DataProcessor>
                        <Properties><Name>Обработка</Name></Properties>
                        <ChildObjects>
                            <Attribute><Properties><Name>Документ</Name></Properties></Attribute>
                            <TabularSection>
                                <Properties><Name>Строки</Name></Properties>
                                <ChildObjects>
                                    <Attribute>
                                        <Properties><Name>Справочник</Name></Properties>
                                    </Attribute>
                                </ChildObjects>
                            </TabularSection>
                        </ChildObjects>
                    </DataProcessor>
                </MetaDataObject>
                """
            ),
            encoding="utf-8",
        )
        module_path = obj_dir / "Module.bsl"
        module_path.write_text("Процедура Метод()\nКонецПроцедуры\n", encoding="utf-8")

        diags = [
            d
            for d in DiagnosticEngine(select={"BSL189"}).check_file(str(module_path))
            if d.code == "BSL189"
        ]

        assert len(diags) == 1
        assert diags[0].message == _rule_msg("BSL189")
        assert (diags[0].line, diags[0].character, diags[0].end_line, diags[0].end_character) == (
            1,
            0,
            1,
            9,
        )

    def test_bsl189_reports_tabular_section_name(self, tmp_path: Path) -> None:
        root = tmp_path / "Config"
        root.mkdir(parents=True)
        (root / "Configuration.xml").write_text("<Configuration/>", encoding="utf-8")
        obj_dir = root / "DataProcessors" / "Обработка" / "Ext"
        obj_dir.mkdir(parents=True)
        (root / "DataProcessors" / "Обработка.xml").write_text(
            textwrap.dedent(
                """\
                <MetaDataObject>
                    <DataProcessor>
                        <Properties><Name>Обработка</Name></Properties>
                        <ChildObjects>
                            <TabularSection>
                                <Properties><Name>Документы</Name></Properties>
                            </TabularSection>
                        </ChildObjects>
                    </DataProcessor>
                </MetaDataObject>
                """
            ),
            encoding="utf-8",
        )
        module_path = obj_dir / "Module.bsl"
        module_path.write_text("Процедура Метод()\nКонецПроцедуры\n", encoding="utf-8")

        diags = [
            d
            for d in DiagnosticEngine(select={"BSL189"}).check_file(str(module_path))
            if d.code == "BSL189"
        ]

        assert len(diags) == 1
        assert diags[0].message == _rule_msg("BSL189")

    def test_bsl189_reports_register_dimension_forbidden_name(self, tmp_path: Path) -> None:
        root = tmp_path / "Config"
        root.mkdir(parents=True)
        (root / "Configuration.xml").write_text("<Configuration/>", encoding="utf-8")
        obj_dir = root / "InformationRegisters" / "Регистр" / "Ext"
        obj_dir.mkdir(parents=True)
        (root / "InformationRegisters" / "Регистр.xml").write_text(
            textwrap.dedent(
                """\
                <MetaDataObject>
                    <InformationRegister>
                        <Properties><Name>Регистр</Name></Properties>
                        <ChildObjects>
                            <Dimension>
                                <Properties><Name>РегистрСведений</Name></Properties>
                            </Dimension>
                        </ChildObjects>
                    </InformationRegister>
                </MetaDataObject>
                """
            ),
            encoding="utf-8",
        )
        module_path = obj_dir / "ManagerModule.bsl"
        module_path.write_text("Процедура Метод()\nКонецПроцедуры\n", encoding="utf-8")

        diags = [
            d
            for d in DiagnosticEngine(select={"BSL189"}).check_file(str(module_path))
            if d.code == "BSL189"
        ]

        assert len(diags) == 1

    def test_bsl189_uses_current_object_without_full_crawl(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = tmp_path / "Config"
        root.mkdir(parents=True)
        (root / "Configuration.xml").write_text("<Configuration/>", encoding="utf-8")
        obj_dir = root / "DataProcessors" / "Обработка" / "Ext"
        obj_dir.mkdir(parents=True)
        (root / "DataProcessors" / "Обработка.xml").write_text(
            textwrap.dedent(
                """\
                <MetaDataObject>
                    <DataProcessor>
                        <Properties><Name>Обработка</Name></Properties>
                        <ChildObjects>
                            <Attribute><Properties><Name>Документ</Name></Properties></Attribute>
                        </ChildObjects>
                    </DataProcessor>
                </MetaDataObject>
                """
            ),
            encoding="utf-8",
        )
        module_path = obj_dir / "Module.bsl"
        module_path.write_text("Процедура Метод()\nКонецПроцедуры\n", encoding="utf-8")
        monkeypatch.setattr(
            "onec_hbk_bsl.analysis.diagnostics._crawl_config_cached",
            lambda *_args, **_kwargs: pytest.fail("full crawl is not expected for BSL189"),
        )

        assert "BSL189" in _codes(DiagnosticEngine(select={"BSL189"}).check_file(str(module_path)))

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
        assert {"BSL213", "BSL231", "BSL242"} <= set(_codes(diags))
        assert "BSL214" not in _codes(diags)
        session_diags = DiagnosticEngine(select={"BSL232"}).check_file(str(session_module))
        assert "BSL232" in _codes(session_diags)

    def test_bsl232_reports_each_protected_module_on_session_module(self, tmp_path: Path) -> None:
        root = tmp_path / "Config"
        root.mkdir(parents=True)
        (root / "Configuration.xml").write_text("<Configuration/>", encoding="utf-8")
        (root / "CommonModules" / "Первый" / "Ext").mkdir(parents=True)
        (root / "CommonModules" / "Второй" / "Ext").mkdir(parents=True)
        (root / "CommonModules" / "Первый.xml").write_text(
            "<CommonModule><Name>Первый</Name><Protected>true</Protected></CommonModule>",
            encoding="utf-8",
        )
        (root / "CommonModules" / "Второй.xml").write_text(
            "<CommonModule><Name>Второй</Name><IsProtected>true</IsProtected></CommonModule>",
            encoding="utf-8",
        )
        session_module = root / "Ext" / "SessionModule.bsl"
        session_module.parent.mkdir(parents=True)
        session_module.write_text(
            "Процедура ПриНачалеРаботыСистемы()\nКонецПроцедуры\n", encoding="utf-8"
        )

        diags = DiagnosticEngine(select={"BSL232"}).check_file(str(session_module))
        bsl232 = [diag for diag in diags if diag.code == "BSL232"]

        assert [(diag.line, diag.character, diag.end_character) for diag in bsl232] == [
            (1, 0, 34),
            (1, 0, 34),
        ]

    def test_bsl214_reports_event_subscription_handler_defects_on_session_module(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path / "Config"
        root.mkdir(parents=True)
        (root / "Configuration.xml").write_text("<Configuration/>", encoding="utf-8")
        (root / "EventSubscriptions").mkdir(parents=True)
        for module_name, server in (
            ("ValidTarget", True),
            ("NonServerTarget", False),
            ("PrivateTarget", True),
        ):
            (root / "CommonModules" / module_name / "Ext").mkdir(parents=True)
            server_xml = "<Server>true</Server>" if server else ""
            (root / "CommonModules" / f"{module_name}.xml").write_text(
                f"<CommonModule><Name>{module_name}</Name>{server_xml}</CommonModule>",
                encoding="utf-8",
            )
        (root / "CommonModules" / "ValidTarget" / "Ext" / "Module.bsl").write_text(
            "Процедура Exists() Экспорт\nКонецПроцедуры\n",
            encoding="utf-8",
        )
        (root / "CommonModules" / "NonServerTarget" / "Ext" / "Module.bsl").write_text(
            "Процедура Exists() Экспорт\nКонецПроцедуры\n",
            encoding="utf-8",
        )
        (root / "CommonModules" / "PrivateTarget" / "Ext" / "Module.bsl").write_text(
            "Процедура Hidden()\nКонецПроцедуры\n",
            encoding="utf-8",
        )
        subscriptions = {
            "Empty": "<EventSubscription><Handler></Handler></EventSubscription>",
            "Malformed": "<EventSubscription><Handler>Broken</Handler></EventSubscription>",
            "MissingModule": (
                "<EventSubscription><Handler>MissingTarget.Exists</Handler></EventSubscription>"
            ),
            "NonServer": (
                "<EventSubscription><Handler>NonServerTarget.Exists</Handler></EventSubscription>"
            ),
            "MissingMethod": (
                "<EventSubscription><Handler>ValidTarget.Absent</Handler></EventSubscription>"
            ),
            "PrivateMethod": (
                "<EventSubscription><Handler>PrivateTarget.Hidden</Handler></EventSubscription>"
            ),
            "Valid": (
                "<EventSubscription><Handler>CommonModule.ValidTarget.Exists</Handler></EventSubscription>"
            ),
        }
        for name, xml in subscriptions.items():
            (root / "EventSubscriptions" / f"{name}.xml").write_text(xml, encoding="utf-8")

        session_module = root / "Ext" / "SessionModule.bsl"
        session_module.parent.mkdir(parents=True)
        session_module.write_text(
            "Процедура ПриНачалеРаботыСистемы()\nКонецПроцедуры\n", encoding="utf-8"
        )
        common_module = root / "CommonModules" / "ValidTarget" / "Ext" / "Module.bsl"

        session_diags = [
            diag
            for diag in DiagnosticEngine(select={"BSL214"}).check_file(str(session_module))
            if diag.code == "BSL214"
        ]

        assert len(session_diags) == 6
        assert {
            (diag.line, diag.character, diag.end_line, diag.end_character) for diag in session_diags
        } == {(1, 0, 1, 9)}
        assert "BSL214" not in _codes(
            DiagnosticEngine(select={"BSL214"}).check_file(str(common_module))
        )

    def test_scheduled_job_handler_skips_split_common_module_file(self, tmp_path: Path) -> None:
        root = tmp_path / "Config"
        root.mkdir(parents=True)
        (root / "Configuration.xml").write_text("<Configuration/>", encoding="utf-8")
        (root / "CommonModules" / "Фоновые" / "Ext").mkdir(parents=True)
        (root / "ScheduledJobs").mkdir(parents=True)
        (root / "CommonModules" / "Фоновые.xml").write_text(
            "<CommonModule><Name>Фоновые</Name><Server>true</Server></CommonModule>",
            encoding="utf-8",
        )
        (root / "ScheduledJobs" / "Задание.xml").write_text(
            "<ScheduledJob><MethodName>CommonModule.Фоновые.Выполнить</MethodName></ScheduledJob>",
            encoding="utf-8",
        )
        split_file = root / "CommonModules" / "Фоновые" / "Ext" / "ДругойМетод.bsl"
        split_file.write_text("Процедура ДругойМетод()\nКонецПроцедуры\n", encoding="utf-8")

        diags = DiagnosticEngine(select={"BSL242"}).check_file(str(split_file))

        assert "BSL242" not in _codes(diags)

    def test_scheduled_job_handler_predefined_false_allows_parameters(self, tmp_path: Path) -> None:
        root = tmp_path / "Config"
        root.mkdir(parents=True)
        (root / "Configuration.xml").write_text("<Configuration/>", encoding="utf-8")
        (root / "CommonModules" / "Фоновые" / "Ext").mkdir(parents=True)
        (root / "ScheduledJobs").mkdir(parents=True)
        (root / "CommonModules" / "Фоновые.xml").write_text(
            "<CommonModule><Name>Фоновые</Name><Server>true</Server></CommonModule>",
            encoding="utf-8",
        )
        (root / "ScheduledJobs" / "Задание.xml").write_text(
            "<ScheduledJob><MethodName>CommonModule.Фоновые.Выполнить</MethodName><Predefined>false</Predefined></ScheduledJob>",
            encoding="utf-8",
        )
        module = root / "CommonModules" / "Фоновые" / "Ext" / "Module.bsl"
        module.write_text(
            "Процедура Выполнить(Параметр) Экспорт\n    Сообщить(Параметр);\nКонецПроцедуры\n",
            encoding="utf-8",
        )

        diags = DiagnosticEngine(select={"BSL242"}).check_file(str(module))

        assert "BSL242" not in _codes(diags)

    def test_scheduled_job_handler_requires_server_common_module(self, tmp_path: Path) -> None:
        root = tmp_path / "Config"
        root.mkdir(parents=True)
        (root / "Configuration.xml").write_text("<Configuration/>", encoding="utf-8")
        (root / "CommonModules" / "Фоновые" / "Ext").mkdir(parents=True)
        (root / "ScheduledJobs").mkdir(parents=True)
        (root / "CommonModules" / "Фоновые.xml").write_text(
            "<CommonModule><Name>Фоновые</Name><Server>false</Server></CommonModule>",
            encoding="utf-8",
        )
        (root / "ScheduledJobs" / "Задание.xml").write_text(
            "<ScheduledJob><MethodName>CommonModule.Фоновые.Выполнить</MethodName></ScheduledJob>",
            encoding="utf-8",
        )
        module = root / "CommonModules" / "Фоновые" / "Ext" / "Module.bsl"
        module.write_text(
            "Процедура Выполнить() Экспорт\n    Сообщить(1);\nКонецПроцедуры\n",
            encoding="utf-8",
        )

        diags = DiagnosticEngine(select={"BSL242"}).check_file(str(module))

        assert "BSL242" in _codes(diags)
        assert next(d.message for d in diags if d.code == "BSL242") == _rule_msg("BSL242")

    def test_scheduled_job_handler_skips_unreferenced_client_common_module(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path / "Config"
        root.mkdir(parents=True)
        (root / "Configuration.xml").write_text("<Configuration/>", encoding="utf-8")
        (root / "CommonModules" / "Клиентский" / "Ext").mkdir(parents=True)
        (root / "ScheduledJobs").mkdir(parents=True)
        (root / "CommonModules" / "Клиентский.xml").write_text(
            "<CommonModule><Name>Клиентский</Name><Server>false</Server><ClientManagedApplication>true</ClientManagedApplication></CommonModule>",
            encoding="utf-8",
        )
        (root / "ScheduledJobs" / "Задание.xml").write_text(
            "<ScheduledJob><MethodName>CommonModule.Другой.Выполнить</MethodName></ScheduledJob>",
            encoding="utf-8",
        )
        module = root / "CommonModules" / "Клиентский" / "Ext" / "Module.bsl"
        module.write_text(
            "Процедура Вспомогательный() Экспорт\n    Сообщить(1);\nКонецПроцедуры\n",
            encoding="utf-8",
        )

        diags = DiagnosticEngine(select={"BSL242"}).check_file(str(module))

        assert "BSL242" not in _codes(diags)

    def test_scheduled_job_handler_empty_method_detected(self, tmp_path: Path) -> None:
        root = tmp_path / "Config"
        root.mkdir(parents=True)
        (root / "Configuration.xml").write_text("<Configuration/>", encoding="utf-8")
        (root / "CommonModules" / "Фоновые" / "Ext").mkdir(parents=True)
        (root / "ScheduledJobs").mkdir(parents=True)
        (root / "CommonModules" / "Фоновые.xml").write_text(
            "<CommonModule><Name>Фоновые</Name><Server>true</Server></CommonModule>",
            encoding="utf-8",
        )
        (root / "ScheduledJobs" / "Задание.xml").write_text(
            "<ScheduledJob><MethodName>CommonModule.Фоновые.Выполнить</MethodName></ScheduledJob>",
            encoding="utf-8",
        )
        module = root / "CommonModules" / "Фоновые" / "Ext" / "Module.bsl"
        module.write_text("Процедура Выполнить() Экспорт\nКонецПроцедуры\n", encoding="utf-8")

        diags = DiagnosticEngine(select={"BSL242"}).check_file(str(module))

        assert "BSL242" in _codes(diags)
        assert next(d.message for d in diags if d.code == "BSL242") == _rule_msg("BSL242")

    @pytest.mark.platform
    @_requires_sdbl
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
                Процедура ТоварыПриАктивизацииСтроки()
                    СерверныйМетод();
                    Соединение = Новый HTTPСоединение("x", 80, "u", "p");
                    Если БезопасныйРежим() И Истина Тогда
                    КонецЕсли;
                    Запрос = Новый Запрос;
                    Запрос.Текст = "ВЫБРАТЬ
                    |  Левое.Тест КАК Поле,
                    |  Левое.Ссылка.Код КАК Код
                    |ИЗ Справочник.НесуществующийСправочник КАК Основание
                    |    ЛЕВОЕ СОЕДИНЕНИЕ Справочник.НесуществующийСправочник КАК Левое
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
        assert {"BSL236", "BSL238", "BSL244", "BSL261"} <= set(_codes(diags))
        assert _codes(diags).count("BSL187") == 1

    def test_bsl244_server_form_event_calling_server_helper_is_clean(self, tmp_path: Path) -> None:
        path = tmp_path / "Catalogs" / "Тест" / "Forms" / "Форма" / "Ext" / "Form" / "Module.bsl"
        path.parent.mkdir(parents=True)
        path.write_text(
            textwrap.dedent(
                """\
                &НаСервере
                Процедура ПриСозданииНаСервере(Отказ, СтандартнаяОбработка)
                    ЗаполнитьДанныеФормы();
                КонецПроцедуры

                &НаСервере
                Процедура ЗаполнитьДанныеФормы()
                КонецПроцедуры
                """
            ),
            encoding="utf-8",
        )

        diags = DiagnosticEngine(select={"BSL244"}).check_file(str(path))

        assert "BSL244" not in _codes(diags)

    def test_bsl244_client_form_event_calling_server_helper_still_reports(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "Catalogs" / "Тест" / "Forms" / "Форма" / "Ext" / "Form" / "Module.bsl"
        path.parent.mkdir(parents=True)
        path.write_text(
            textwrap.dedent(
                """\
                &НаКлиенте
                Процедура ТоварыПриАктивизацииСтроки()
                    ЗаполнитьДанныеФормы();
                КонецПроцедуры

                &НаСервере
                Процедура ЗаполнитьДанныеФормы()
                КонецПроцедуры
                """
            ),
            encoding="utf-8",
        )

        diags = DiagnosticEngine(select={"BSL244"}).check_file(str(path))

        assert "BSL244" in _codes(diags)

    def test_bsl244_other_form_event_calling_server_helper_is_clean(self, tmp_path: Path) -> None:
        path = tmp_path / "Catalogs" / "Тест" / "Forms" / "Форма" / "Ext" / "Form" / "Module.bsl"
        path.parent.mkdir(parents=True)
        path.write_text(
            textwrap.dedent(
                """\
                &НаКлиенте
                Процедура ПриОткрытии()
                    ЗаполнитьДанныеФормы();
                КонецПроцедуры

                &НаСервере
                Процедура ЗаполнитьДанныеФормы()
                КонецПроцедуры
                """
            ),
            encoding="utf-8",
        )

        diags = DiagnosticEngine(select={"BSL244"}).check_file(str(path))

        assert "BSL244" not in _codes(diags)

    def test_bsl244_server_no_context_target_is_clean(self, tmp_path: Path) -> None:
        path = tmp_path / "Catalogs" / "Тест" / "Forms" / "Форма" / "Ext" / "Form" / "Module.bsl"
        path.parent.mkdir(parents=True)
        path.write_text(
            textwrap.dedent(
                """\
                &НаКлиенте
                Процедура ТоварыНачалоВыбора()
                    ЗаполнитьДанныеФормы();
                КонецПроцедуры

                &НаСервереБезКонтекста
                Процедура ЗаполнитьДанныеФормы()
                КонецПроцедуры
                """
            ),
            encoding="utf-8",
        )

        diags = DiagnosticEngine(select={"BSL244"}).check_file(str(path))

        assert "BSL244" not in _codes(diags)

    def test_bsl244_qualified_call_is_clean(self, tmp_path: Path) -> None:
        path = tmp_path / "Catalogs" / "Тест" / "Forms" / "Форма" / "Ext" / "Form" / "Module.bsl"
        path.parent.mkdir(parents=True)
        path.write_text(
            textwrap.dedent(
                """\
                &НаКлиенте
                Процедура ТоварыНачалоВыбора()
                    ОбщегоНазначения.ЗаполнитьДанныеФормы();
                КонецПроцедуры

                &НаСервере
                Процедура ЗаполнитьДанныеФормы()
                КонецПроцедуры
                """
            ),
            encoding="utf-8",
        )

        diags = DiagnosticEngine(select={"BSL244"}).check_file(str(path))

        assert "BSL244" not in _codes(diags)

    def test_bsl244_english_forbidden_event_reports(self, tmp_path: Path) -> None:
        path = tmp_path / "Catalogs" / "Тест" / "Forms" / "Форма" / "Ext" / "Form" / "Module.bsl"
        path.parent.mkdir(parents=True)
        path.write_text(
            textwrap.dedent(
                """\
                &AtClient
                Procedure ItemsOnStartChoice()
                    FillData();
                EndProcedure

                &AtServer
                Procedure FillData()
                EndProcedure
                """
            ),
            encoding="utf-8",
        )

        diags = DiagnosticEngine(select={"BSL244"}).check_file(str(path))

        assert "BSL244" in _codes(diags)

    @pytest.mark.platform
    @_requires_sdbl
    def test_bsl187_reports_left_join_field_without_isnull(self, tmp_path: Path) -> None:
        path = tmp_path / "DataProcessors" / "Обработка" / "Ext" / "ObjectModule.bsl"
        path.parent.mkdir(parents=True)
        path.write_text(
            textwrap.dedent(
                """\
                Процедура Метод()
                    Запрос = Новый Запрос;
                    Запрос.Текст = "ВЫБРАТЬ
                    |  Левое.Тест КАК Поле
                    |ИЗ Справочник.Тест КАК Основание
                    |    ЛЕВОЕ СОЕДИНЕНИЕ Справочник.Тест КАК Левое
                    |    ПО Истина";
                КонецПроцедуры
                """
            ),
            encoding="utf-8",
        )

        diags = DiagnosticEngine(select={"BSL187"}).check_file(str(path))

        bsl187 = [diag for diag in diags if diag.code == "BSL187"]
        assert len(bsl187) == 1
        assert bsl187[0].line == 6

    @pytest.mark.platform
    @_requires_sdbl
    def test_bsl187_skips_field_inside_isnull(self, tmp_path: Path) -> None:
        content = """\
            Запрос.Текст =
            "ВЫБРАТЬ
            |  ЕСТЬNULL(Левое.Тест, 0) КАК Поле
            |ИЗ Справочник.Тест КАК Основание
            |    ЛЕВОЕ СОЕДИНЕНИЕ Справочник.Тест КАК Левое
            |    ПО Основание.Ссылка = Левое.Ссылка";
        """

        diags = _check(content, tmp_path, select={"BSL187"})

        assert "BSL187" not in _codes(diags)

    @pytest.mark.platform
    @_requires_sdbl
    def test_bsl187_skips_alias_checked_not_null_in_where(self, tmp_path: Path) -> None:
        content = """\
            Запрос.Текст =
            "ВЫБРАТЬ
            |  Левое.Тест КАК Поле
            |ИЗ Справочник.Тест КАК Основание
            |    ЛЕВОЕ СОЕДИНЕНИЕ Справочник.Тест КАК Левое
            |    ПО Основание.Ссылка = Левое.Ссылка
            |ГДЕ Левое.Ссылка ЕСТЬ НЕ NULL";
        """

        diags = _check(content, tmp_path, select={"BSL187"})

        assert "BSL187" not in _codes(diags)

    @pytest.mark.platform
    @_requires_sdbl
    def test_bsl187_skips_alias_checked_not_null_by_parenthesized_not(self, tmp_path: Path) -> None:
        content = """\
            Запрос.Текст =
            "ВЫБРАТЬ
            |  Левое.Тест КАК Поле
            |ИЗ Справочник.Тест КАК Основание
            |    ЛЕВОЕ СОЕДИНЕНИЕ Справочник.Тест КАК Левое
            |    ПО Основание.Ссылка = Левое.Ссылка
            |ГДЕ (НЕ (Левое.Ссылка ЕСТЬ NULL))";
        """

        diags = _check(content, tmp_path, select={"BSL187"})

        assert "BSL187" not in _codes(diags)

    @pytest.mark.platform
    @_requires_sdbl
    def test_bsl187_skips_invalid_sdbl_tree(self, tmp_path: Path) -> None:
        content = """\
            Запрос.Текст =
            "ВЫБРАТЬ
            |  Левое.Тест КАК Поле
            |ИЗ Справочник.Тест КАК Основание
            |    ЛЕВОЕ СОЕДИНЕНИЕ
            |    ПО Истина";
        """

        diags = _check(content, tmp_path, select={"BSL187"})

        assert "BSL187" not in _codes(diags)

    @pytest.mark.platform
    @_requires_sdbl
    def test_bsl187_reports_right_and_full_join_nullable_sides(self, tmp_path: Path) -> None:
        content = """\
            Запрос.Текст =
            "ВЫБРАТЬ
            |  Основание.Тест КАК Поле1,
            |  Правое.Тест КАК Поле2
            |ИЗ Справочник.Тест КАК Основание
            |    ПРАВОЕ СОЕДИНЕНИЕ Справочник.Тест КАК Правое
            |    ПО Основание.Ссылка = Правое.Ссылка";

            Запрос.Текст =
            "ВЫБРАТЬ
            |  ПолноеЛевое.Тест КАК Поле2,
            |  ПолноеПравое.Тест КАК Поле3
            |ИЗ Справочник.Тест КАК ПолноеЛевое
            |    ПОЛНОЕ СОЕДИНЕНИЕ Справочник.Тест КАК ПолноеПравое
            |    ПО ПолноеЛевое.Ссылка = ПолноеПравое.Ссылка";
        """

        diags = [
            diag for diag in _check(content, tmp_path, select={"BSL187"}) if diag.code == "BSL187"
        ]

        assert [(diag.line, diag.character) for diag in diags] == [(6, 5), (14, 5)]

    @pytest.mark.platform
    @_requires_sdbl
    def test_bsl187_reports_union_join_from_recovered_sdbl_tree(self, tmp_path: Path) -> None:
        content = """\
            Запрос.Текст =
            "ВЫБРАТЬ
            |  Таблица.Ссылка КАК Ссылка
            |ИЗ Таблица КАК Таблица
            |
            |ОБЪЕДИНИТЬ ВСЕ
            |
            |ВЫБРАТЬ
            |  Таблица.Ссылка КАК Ссылка,
            |  Левое.Ссылка КАК Ссылка1
            |ИЗ Справочник.Тест КАК Таблица
            |    ЛЕВОЕ СОЕДИНЕНИЕ Справочник.Тест КАК Левое
            |    ПО Таблица.Ссылка = Левое.Ссылка";
        """

        diags = [
            diag for diag in _check(content, tmp_path, select={"BSL187"}) if diag.code == "BSL187"
        ]

        assert [(diag.line, diag.character) for diag in diags] == [(12, 5)]

    def test_bsl191_reports_full_outer_join_phrase(self, tmp_path: Path) -> None:
        content = """\
            Запрос.Текст =
            "ВЫБРАТЬ
            |  Левое.Ссылка КАК Ссылка
            |ИЗ Справочник.Тест КАК Левое
            |    ПОЛНОЕ ВНЕШНЕЕ СОЕДИНЕНИЕ Справочник.Тест КАК Правое
            |    ПО Левое.Ссылка = Правое.Ссылка";
        """

        diags = [
            diag for diag in _check(content, tmp_path, select={"BSL191"}) if diag.code == "BSL191"
        ]

        assert [
            (diag.line, diag.character, diag.end_line, diag.end_character) for diag in diags
        ] == [(5, 5, 5, 30)]

    def test_bsl191_skips_left_join(self, tmp_path: Path) -> None:
        content = """\
            Запрос.Текст =
            "ВЫБРАТЬ
            |  Левое.Ссылка КАК Ссылка
            |ИЗ Справочник.Тест КАК Левое
            |    ЛЕВОЕ СОЕДИНЕНИЕ Справочник.Тест КАК Правое
            |    ПО Левое.Ссылка = Правое.Ссылка";
        """

        diags = _check(content, tmp_path, select={"BSL191"})

        assert "BSL191" not in _codes(diags)

    def test_bsl236_uses_full_metadata_source_name(self, tmp_path: Path) -> None:
        path = tmp_path / "DataProcessors" / "Обработка" / "Ext" / "ObjectModule.bsl"
        path.parent.mkdir(parents=True)
        (tmp_path / "Configuration.xml").write_text("<Configuration/>", encoding="utf-8")
        (tmp_path / "DataProcessors").mkdir(exist_ok=True)
        (tmp_path / "DataProcessors" / "Обработка.xml").write_text(
            "<MetaDataObject><DataProcessor><Properties><Name>Обработка</Name></Properties></DataProcessor></MetaDataObject>",
            encoding="utf-8",
        )
        path.write_text(
            textwrap.dedent(
                """\
                Процедура Тест()
                    Запрос = Новый Запрос;
                    Запрос.Текст = "ВЫБРАТЬ
                    |   Таблица.Ссылка
                    |ИЗ
                    |   Документ.АктСверкиВзаиморасчетов КАК Таблица";
                КонецПроцедуры
                """
            ),
            encoding="utf-8",
        )

        diags = [
            d
            for d in DiagnosticEngine(select={"BSL236"}).check_file(str(path))
            if d.code == "BSL236"
        ]

        assert len(diags) == 1
        assert diags[0].line == 6
        assert diags[0].character == 8
        assert diags[0].end_character == 8 + len("Документ.АктСверкиВзаиморасчетов")
        assert diags[0].message == _rule_msg("BSL236")

    def test_bsl236_known_dotted_metadata_source_is_clean(self, tmp_path: Path) -> None:
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
                    |   Таблица.Ссылка
                    |ИЗ
                    |   Справочник.Тест КАК Таблица";
                КонецПроцедуры
                """
            ),
            encoding="utf-8",
        )

        diags = [
            d
            for d in DiagnosticEngine(select={"BSL236"}).check_file(str(path))
            if d.code == "BSL236"
        ]

        assert diags == []

    def test_bsl236_same_name_in_different_metadata_type_does_not_satisfy_reference(
        self, tmp_path: Path
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
                    |   Таблица.Ссылка
                    |ИЗ
                    |   Документ.Тест КАК Таблица";
                КонецПроцедуры
                """
            ),
            encoding="utf-8",
        )

        diags = [
            d
            for d in DiagnosticEngine(select={"BSL236"}).check_file(str(path))
            if d.code == "BSL236"
        ]

        assert len(diags) == 1
        assert diags[0].line == 6
        assert diags[0].character == 8
        assert diags[0].end_character == 8 + len("Документ.Тест")

    def test_bsl236_uses_active_configuration_root_only(self, tmp_path: Path) -> None:
        workspace = tmp_path
        (workspace / ".git").mkdir()
        extension_root = workspace / "src" / "extension"
        framework_root = workspace / "src" / "framework"
        path = extension_root / "DataProcessors" / "Обработка" / "Ext" / "ObjectModule.bsl"
        path.parent.mkdir(parents=True)
        (extension_root / "Configuration.xml").parent.mkdir(parents=True, exist_ok=True)
        (extension_root / "Configuration.xml").write_text("<Configuration/>", encoding="utf-8")
        (extension_root / "DataProcessors").mkdir(exist_ok=True)
        (extension_root / "DataProcessors" / "Обработка.xml").write_text(
            "<MetaDataObject><DataProcessor><Properties><Name>Обработка</Name></Properties></DataProcessor></MetaDataObject>",
            encoding="utf-8",
        )
        (framework_root / "Configuration.xml").parent.mkdir(parents=True, exist_ok=True)
        (framework_root / "Configuration.xml").write_text("<Configuration/>", encoding="utf-8")
        (framework_root / "Documents").mkdir(exist_ok=True)
        (framework_root / "Documents" / "РеализацияТоваровУслуг.xml").write_text(
            "<MetaDataObject><Document><Properties><Name>РеализацияТоваровУслуг</Name></Properties></Document></MetaDataObject>",
            encoding="utf-8",
        )
        path.write_text(
            textwrap.dedent(
                """\
                Процедура Тест()
                    Запрос = Новый Запрос;
                    Запрос.Текст = "ВЫБРАТЬ
                    |   Таблица.Ссылка
                    |ИЗ
                    |   Документ.РеализацияТоваровУслуг КАК Таблица
                    |ОБЪЕДИНИТЬ ВСЕ
                    |ВЫБРАТЬ
                    |   Таблица.Ссылка
                    |ИЗ
                    |   Документ.АктСверкиВзаиморасчетов КАК Таблица";
                КонецПроцедуры
                """
            ),
            encoding="utf-8",
        )

        diags = [
            d
            for d in DiagnosticEngine(select={"BSL236"}).check_file(str(path))
            if d.code == "BSL236"
        ]

        assert len(diags) == 2
        assert [(diag.line, diag.character, diag.end_character) for diag in diags] == [
            (6, 8, 8 + len("Документ.РеализацияТоваровУслуг")),
            (11, 8, 8 + len("Документ.АктСверкиВзаиморасчетов")),
        ]
        assert {diag.message for diag in diags} == {_rule_msg("BSL236")}

    def test_bsl236_does_not_use_unrelated_workspace_configuration_roots(
        self, tmp_path: Path
    ) -> None:
        workspace = tmp_path
        (workspace / ".git").mkdir()
        extension_root = workspace / "src" / "extension"
        spec_root = workspace / "spec" / "xunit-db-src"
        path = extension_root / "DataProcessors" / "Обработка" / "Ext" / "ObjectModule.bsl"
        path.parent.mkdir(parents=True)
        (extension_root / "Configuration.xml").parent.mkdir(parents=True, exist_ok=True)
        (extension_root / "Configuration.xml").write_text("<Configuration/>", encoding="utf-8")
        (extension_root / "DataProcessors").mkdir(exist_ok=True)
        (extension_root / "DataProcessors" / "Обработка.xml").write_text(
            "<MetaDataObject><DataProcessor><Properties><Name>Обработка</Name></Properties></DataProcessor></MetaDataObject>",
            encoding="utf-8",
        )
        (spec_root / "Configuration.xml").parent.mkdir(parents=True, exist_ok=True)
        (spec_root / "Configuration.xml").write_text("<Configuration/>", encoding="utf-8")
        (spec_root / "Catalogs").mkdir(exist_ok=True)
        (spec_root / "Catalogs" / "ТестЭДО_ЮрФизЛица.xml").write_text(
            "<MetaDataObject><Catalog><Properties><Name>ТестЭДО_ЮрФизЛица</Name></Properties></Catalog></MetaDataObject>",
            encoding="utf-8",
        )
        path.write_text(
            textwrap.dedent(
                """\
                Процедура Тест()
                    Запрос.Текст = "ВЫБРАТЬ
                    |   Таблица.Ссылка
                    |ИЗ
                    |   Справочник.ТестЭДО_ЮрФизЛица КАК Таблица";
                КонецПроцедуры
                """
            ),
            encoding="utf-8",
        )

        diags = [
            d
            for d in DiagnosticEngine(select={"BSL236"}).check_file(str(path))
            if d.code == "BSL236"
        ]

        assert len(diags) == 1
        assert diags[0].line == 5
        assert diags[0].character == 8
        assert diags[0].end_character == 8 + len("Справочник.ТестЭДО_ЮрФизЛица")
        assert diags[0].message == _rule_msg("BSL236")

    def test_bsl236_reports_missing_metadata_type_references(self, tmp_path: Path) -> None:
        path = tmp_path / "DataProcessors" / "Обработка" / "Ext" / "ObjectModule.bsl"
        path.parent.mkdir(parents=True)
        (tmp_path / "Configuration.xml").write_text("<Configuration/>", encoding="utf-8")
        (tmp_path / "DataProcessors").mkdir(exist_ok=True)
        (tmp_path / "DataProcessors" / "Обработка.xml").write_text(
            "<MetaDataObject><DataProcessor><Properties><Name>Обработка</Name></Properties></DataProcessor></MetaDataObject>",
            encoding="utf-8",
        )
        path.write_text(
            textwrap.dedent(
                """\
                Процедура Тест()
                    Запрос.Текст = "ВЫБРАТЬ
                    |   ВЫРАЗИТЬ(Данные.Ссылка КАК Документ.СчетФактура).Дата КАК Дата,
                    |   ВЫБОР КОГДА Данные.Единица ССЫЛКА Справочник.ЕдиницыИзмерения ТОГДА 1 ИНАЧЕ 0 КОНЕЦ КАК ЭтоЕдиница
                    |ИЗ
                    |   ВТ_Данные КАК Данные";
                КонецПроцедуры
                """
            ),
            encoding="utf-8",
        )

        diags = [
            d
            for d in DiagnosticEngine(select={"BSL236"}).check_file(str(path))
            if d.code == "BSL236"
        ]

        assert {diag.message for diag in diags} == {_rule_msg("BSL236")}
        assert {(diag.line, diag.character, diag.end_character) for diag in diags} == {
            (3, 35, 35 + len("Документ.СчетФактура")),
            (4, 42, 42 + len("Справочник.ЕдиницыИзмерения")),
        }

    def test_bsl236_reports_missing_virtual_table_metadata_source(self, tmp_path: Path) -> None:
        path = tmp_path / "DataProcessors" / "Обработка" / "Ext" / "ObjectModule.bsl"
        path.parent.mkdir(parents=True)
        (tmp_path / "Configuration.xml").write_text("<Configuration/>", encoding="utf-8")
        (tmp_path / "DataProcessors").mkdir(exist_ok=True)
        (tmp_path / "DataProcessors" / "Обработка.xml").write_text(
            "<MetaDataObject><DataProcessor><Properties><Name>Обработка</Name></Properties></DataProcessor></MetaDataObject>",
            encoding="utf-8",
        )
        path.write_text(
            textwrap.dedent(
                """\
                Процедура Тест()
                    Запрос.Текст = "ВЫБРАТЬ
                    |   Таблица.Ссылка
                    |ИЗ
                    |   РегистрСведений.УдаленныйРегистр.СрезПоследних(&Дата) КАК Таблица";
                КонецПроцедуры
                """
            ),
            encoding="utf-8",
        )

        diags = [
            d
            for d in DiagnosticEngine(select={"BSL236"}).check_file(str(path))
            if d.code == "BSL236"
        ]

        assert len(diags) == 1
        assert diags[0].line == 5
        assert diags[0].character == 8
        assert diags[0].end_character == 8 + len("РегистрСведений.УдаленныйРегистр")

    def test_bsl236_skips_temp_tables_declared_by_place_into(self, tmp_path: Path) -> None:
        path = tmp_path / "DataProcessors" / "Обработка" / "Ext" / "ObjectModule.bsl"
        path.parent.mkdir(parents=True)
        (tmp_path / "Configuration.xml").write_text("<Configuration/>", encoding="utf-8")
        (tmp_path / "DataProcessors").mkdir(exist_ok=True)
        (tmp_path / "DataProcessors" / "Обработка.xml").write_text(
            "<MetaDataObject><DataProcessor><Properties><Name>Обработка</Name></Properties></DataProcessor></MetaDataObject>",
            encoding="utf-8",
        )
        path.write_text(
            textwrap.dedent(
                """\
                Процедура Тест()
                    Запрос.Текст = "ВЫБРАТЬ
                    |   Таблица.Ссылка
                    |ПОМЕСТИТЬ ТаблицаДокумента
                    |ИЗ
                    |   Документ.РасходнаяНакладная КАК Таблица";
                    Запрос.Текст = "ВЫБРАТЬ
                    |   ТаблицаДокумента.Ссылка
                    |ИЗ
                    |   ТаблицаДокумента КАК ТаблицаДокумента";
                КонецПроцедуры
                """
            ),
            encoding="utf-8",
        )

        diags = [
            d
            for d in DiagnosticEngine(select={"BSL236"}).check_file(str(path))
            if d.code == "BSL236"
        ]

        assert len(diags) == 1
        assert diags[0].line == 6
        assert diags[0].character == 8
        assert diags[0].end_character == 8 + len("Документ.РасходнаяНакладная")
        assert diags[0].message == _rule_msg("BSL236")

    def test_bsl236_skips_single_part_query_sources(self, tmp_path: Path) -> None:
        path = tmp_path / "DataProcessors" / "Обработка" / "Ext" / "ObjectModule.bsl"
        path.parent.mkdir(parents=True)
        (tmp_path / "Configuration.xml").write_text("<Configuration/>", encoding="utf-8")
        (tmp_path / "DataProcessors").mkdir(exist_ok=True)
        (tmp_path / "DataProcessors" / "Обработка.xml").write_text(
            "<MetaDataObject><DataProcessor><Properties><Name>Обработка</Name></Properties></DataProcessor></MetaDataObject>",
            encoding="utf-8",
        )
        path.write_text(
            textwrap.dedent(
                """\
                Процедура Тест()
                    Запрос.Текст = "ВЫБРАТЬ
                    |   НастройкиЭДО.Ссылка
                    |ИЗ
                    |   НастройкиЭДО КАК НастройкиЭДО";
                КонецПроцедуры
                """
            ),
            encoding="utf-8",
        )

        diags = [
            d
            for d in DiagnosticEngine(select={"BSL236"}).check_file(str(path))
            if d.code == "BSL236"
        ]

        assert diags == []

    def test_bsl236_does_not_treat_section_after_commented_from_source_as_metadata(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "DataProcessors" / "Обработка" / "Ext" / "ObjectModule.bsl"
        path.parent.mkdir(parents=True)
        (tmp_path / "Configuration.xml").write_text("<Configuration/>", encoding="utf-8")
        (tmp_path / "DataProcessors").mkdir(exist_ok=True)
        (tmp_path / "DataProcessors" / "Обработка.xml").write_text(
            "<MetaDataObject><DataProcessor><Properties><Name>Обработка</Name></Properties></DataProcessor></MetaDataObject>",
            encoding="utf-8",
        )
        path.write_text(
            textwrap.dedent(
                """\
                Процедура Тест()
                    Запрос.Текст = "ВЫБРАТЬ
                    |   Данные.Ссылка
                    |ИЗ
                    |   //Документ.ТестовыйДокумент КАК Данные
                    |
                    |ГДЕ
                    |   Данные.Ссылка = &Ссылка";
                КонецПроцедуры
                """
            ),
            encoding="utf-8",
        )

        diags = [
            d
            for d in DiagnosticEngine(select={"BSL236"}).check_file(str(path))
            if d.code == "BSL236"
        ]

        assert diags == []

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

    def test_bsl238_reports_chain_ending_with_ref_like_bslls(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Запрос = Новый Запрос;
                Запрос.Текст = "ВЫБРАТЬ
                |  Таблица.Код
                |ИЗ Справочник.Тест КАК Таблица
                |ГДЕ
                |  Таблица.Реквизит.Ссылка ЕСТЬ НЕ NULL";
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL238"}) if d.code == "BSL238"]
        assert len(diags) == 1
        assert diags[0].line == 7
        assert diags[0].message == _rule_msg("BSL238")

    def test_bsl238_does_not_report_plain_table_ref(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Запрос = Новый Запрос;
                Запрос.Текст = "ВЫБРАТЬ
                |  Таблица.Ссылка
                |ИЗ Справочник.Тест КАК Таблица";
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL238"})
        assert "BSL238" not in _codes(diags)

    def test_bsl238_skips_temp_table_ref_field_like_bslls(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Запрос = Новый Запрос;
                Запрос.Текст = "ВЫБРАТЬ
                |  КОГДА ДанныеДокумента.Ссылка.СуммаВключаетНДС
                |    ТОГДА ДанныеДокумента.Сумма
                |ИЗ
                |  ДанныеДокумента КАК ДанныеДокумента";
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL238"})
        assert "BSL238" not in _codes(diags)

    def test_bsl238_skips_aliased_simple_source_ref_field_like_bslls(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Запрос = Новый Запрос;
                Запрос.Текст = "ВЫБРАТЬ
                |  Данные.Ссылка.МоментВремени КАК МоментВремени
                |ИЗ
                |  ВременнаяТаблица КАК Данные";
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL238"})
        assert "BSL238" not in _codes(diags)

    def test_bsl238_skips_tabular_section_ref_field_like_bslls(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Запрос = Новый Запрос;
                Запрос.Текст = "ВЫБРАТЬ
                |  Документ.Ссылка
                |ИЗ
                |  Документ.ОтчетОРозничныхПродажах КАК Документ
                |    ЛЕВОЕ СОЕДИНЕНИЕ Документ.ОтчетОРозничныхПродажах.Товары КАК Товары
                |    ПО Документ.Ссылка = Товары.Ссылка.Дата";
            КонецПроцедуры
        """
        diags = _check(content, tmp_path, select={"BSL238"})
        assert "BSL238" not in _codes(diags)

    def test_bsl238_reports_nested_ref_after_tabular_section_ref_like_bslls(
        self, tmp_path: Path
    ) -> None:
        content = """\
            Процедура Тест()
                Запрос = Новый Запрос;
                Запрос.Текст = "ВЫБРАТЬ
                |  Товары.Ссылка.Номенклатура.Ссылка КАК Номенклатура
                |ИЗ
                |  Документ.Тест.Товары КАК Товары";
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL238"}) if d.code == "BSL238"]
        assert len(diags) == 1
        assert diags[0].line == 4

    def test_bsl238_reports_unknown_source_ref_chain_like_bslls(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Запрос = Новый Запрос;
                Запрос.Текст = "ВЫБРАТЬ
                |  СтарыйИсточник.Ссылка.Код КАК Код
                |ИЗ
                |  Документ.Тест.Товары КАК Товары";
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL238"}) if d.code == "BSL238"]
        assert len(diags) == 1
        assert diags[0].line == 4

    def test_bsl238_keeps_source_aliases_scoped_to_query(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Запрос = Новый Запрос;
                Запрос.Текст = "ВЫБРАТЬ
                |  Товары.Ссылка
                |ИЗ
                |  Документ.Тест.Товары КАК Товары
                |;
                |ВЫБРАТЬ
                |  Товары.Ссылка.Код
                |ИЗ
                |  Документ.ДругойТест.Товары КАК ДругиеТовары";
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL238"}) if d.code == "BSL238"]
        assert [(d.line, d.character) for d in diags] == [(9, 7)]

    @pytest.mark.platform
    @_requires_sdbl
    def test_bsl077_reports_top_in_package_before_later_order_by(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Запрос = Новый Запрос;
                Запрос.Текст = "ВЫБРАТЬ ПЕРВЫЕ 1000
                |  Таблица.Ссылка
                |ПОМЕСТИТЬ ВТ
                |ИЗ Справочник.Тест КАК Таблица
                |;
                |
                |ВЫБРАТЬ
                |  ВТ.Ссылка
                |ИЗ ВТ КАК ВТ
                |УПОРЯДОЧИТЬ ПО
                |  ВТ.Ссылка";
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL077"}) if d.code == "BSL077"]
        assert [(d.line, d.character, d.end_character) for d in diags] == [(3, 28, 39)]

    @pytest.mark.platform
    @_requires_sdbl
    def test_bsl077_skips_top_in_separate_ordered_package(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Запрос = Новый Запрос;
                Запрос.Текст = "ВЫБРАТЬ ПЕРВЫЕ 1000
                |  Таблица.Ссылка
                |ИЗ Справочник.Тест КАК Таблица
                |;
                |
                |ВЫБРАТЬ ПЕРВЫЕ 1000
                |  Таблица.Ссылка
                |ИЗ Справочник.Тест КАК Таблица
                |УПОРЯДОЧИТЬ ПО
                |  Таблица.Ссылка";
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL077"}) if d.code == "BSL077"]
        assert [(d.line, d.character, d.end_character) for d in diags] == [(3, 28, 39)]

    @pytest.mark.platform
    @_requires_sdbl
    def test_bsl077_skips_ordered_top_into_query_with_temporary_table(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Запрос = Новый Запрос;
                Запрос.Текст = "ВЫБРАТЬ РАЗРЕШЕННЫЕ ПЕРВЫЕ 1
                |  Источник.Ссылка КАК Документ,
                |  Источник.ДатаСобытия
                |ПОМЕСТИТЬ ВТ_ПоследнееСобытие
                |ИЗ
                |  Документ.ТестовыйДокумент.События КАК Источник
                |ГДЕ
                |  Источник.Ссылка = &СсылкаНаОбъект
                |УПОРЯДОЧИТЬ ПО
                |  ДатаСобытия УБЫВ;
                |
                |ВЫБРАТЬ
                |  ВТ_ПоследнееСобытие.Документ
                |ИЗ ВТ_ПоследнееСобытие КАК ВТ_ПоследнееСобытие";
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL077"}) if d.code == "BSL077"]
        assert diags == []

    @pytest.mark.platform
    @_requires_sdbl
    def test_bsl077_reports_union_top_one_without_where(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Запрос.Текст = "ВЫБРАТЬ ПЕРВЫЕ 1
                |  Таблица.Ссылка
                |ИЗ Справочник.Тест КАК Таблица
                |
                |ОБЪЕДИНИТЬ ВСЕ
                |
                |ВЫБРАТЬ
                |  ДругаяТаблица.Ссылка
                |ИЗ Справочник.ДругойТест КАК ДругаяТаблица";
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL077"}) if d.code == "BSL077"]
        assert [(d.line, d.character, d.end_character) for d in diags] == [(2, 28, 36)]

    @pytest.mark.platform
    @_requires_sdbl
    def test_bsl077_skips_union_top_one_with_where_like_bslls(self, tmp_path: Path) -> None:
        content = """\
            Процедура Тест()
                Запрос.Текст = "ВЫБРАТЬ ПЕРВЫЕ 1
                |  Таблица.Ссылка
                |ИЗ Справочник.Тест КАК Таблица
                |ГДЕ Таблица.Ссылка = &Ссылка
                |
                |ОБЪЕДИНИТЬ ВСЕ
                |
                |ВЫБРАТЬ
                |  ДругаяТаблица.Ссылка
                |ИЗ Справочник.ДругойТест КАК ДругаяТаблица";
            КонецПроцедуры
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL077"}) if d.code == "BSL077"]
        assert diags == []

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
        diags = DiagnosticEngine(select={"BSL246"}).check_file(str(app_module))
        assert "BSL246" in _codes(diags)

    def test_bsl246_full_access_roles_are_clean(self, tmp_path: Path) -> None:
        root = tmp_path / "Config"
        root.mkdir(parents=True)
        (root / "Configuration.xml").write_text("<Configuration/>", encoding="utf-8")
        roles = root / "Roles"
        roles.mkdir()
        (roles / "FullAccess.xml").write_text(
            "<Role><SetForNewObjects>true</SetForNewObjects></Role>",
            encoding="utf-8",
        )
        (roles / "ПолныеПрава.xml").write_text(
            "<Role><SetForNewObjects>true</SetForNewObjects></Role>",
            encoding="utf-8",
        )
        app_module = root / "Ext" / "ManagedApplicationModule.bsl"
        app_module.parent.mkdir(parents=True)
        app_module.write_text(
            "Процедура ПриНачалеРаботыСистемы()\nКонецПроцедуры\n", encoding="utf-8"
        )

        diags = DiagnosticEngine(select={"BSL246"}).check_file(str(app_module))

        assert "BSL246" not in _codes(diags)

    def test_bsl246_non_managed_module_is_clean(self, tmp_path: Path) -> None:
        root = tmp_path / "Config"
        root.mkdir(parents=True)
        (root / "Configuration.xml").write_text("<Configuration/>", encoding="utf-8")
        roles = root / "Roles"
        roles.mkdir()
        (roles / "Users.xml").write_text(
            "<Role><SetForNewObjects>true</SetForNewObjects></Role>",
            encoding="utf-8",
        )
        ordinary_module = root / "CommonModules" / "Обычный" / "Ext" / "Module.bsl"
        ordinary_module.parent.mkdir(parents=True)
        ordinary_module.write_text("Процедура Метод()\nКонецПроцедуры\n", encoding="utf-8")

        diags = DiagnosticEngine(select={"BSL246"}).check_file(str(ordinary_module))

        assert "BSL246" not in _codes(diags)

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
        (root / "CommonModules" / "Привилегированный" / "Ext" / "Module.bsl").write_text(
            "Процедура Метод() Экспорт\nКонецПроцедуры\nПроцедура Приватный()\nКонецПроцедуры\n",
            encoding="utf-8",
        )
        ordinary_module = root / "CommonModules" / "Обычный" / "Ext" / "Module.bsl"
        ordinary_module.write_text(
            "Процедура НетЭкспорта()\n"
            "    Привилегированный.Метод();\n"
            "    Привилегированный.Приватный();\n"
            "КонецПроцедуры\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "onec_hbk_bsl.analysis.diagnostics._common_module_privileged_map_cached",
            lambda *_args, **_kwargs: pytest.fail(
                "BSL231 should use per-module privileged lookup, not full privileged index"
            ),
        )
        diags = DiagnosticEngine(select={"BSL231"}).check_file(str(ordinary_module))
        bsl231 = [diag for diag in diags if diag.code == "BSL231"]
        assert [(diag.line, diag.character, diag.end_character) for diag in bsl231] == [(2, 22, 27)]

    def test_bsl231_reports_nested_public_calls_inside_privileged_module(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path / "Config"
        root.mkdir(parents=True)
        (root / "Configuration.xml").write_text("<Configuration/>", encoding="utf-8")
        (root / "CommonModules" / "Привилегированный" / "Ext").mkdir(parents=True)
        (root / "CommonModules" / "Привилегированный.xml").write_text(
            "<CommonModule><Name>Привилегированный</Name><Privileged>true</Privileged></CommonModule>",
            encoding="utf-8",
        )
        privileged_module = root / "CommonModules" / "Привилегированный" / "Ext" / "Module.bsl"
        privileged_module.write_text(
            "Функция ПубличнаяФункция() Экспорт\nКонецФункции\n"
            "Процедура ПриватнаяПроцедура()\n"
            "    ПубличнаяФункция();\n"
            "КонецПроцедуры\n",
            encoding="utf-8",
        )
        diags = DiagnosticEngine(select={"BSL231"}).check_file(str(privileged_module))
        bsl231 = [diag for diag in diags if diag.code == "BSL231"]
        assert [(diag.line, diag.character, diag.end_character) for diag in bsl231] == [(4, 4, 20)]

    def test_bsl231_plain_common_module_without_dotted_calls_skips_privileged_index(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = tmp_path / "Config"
        root.mkdir(parents=True)
        (root / "Configuration.xml").write_text("<Configuration/>", encoding="utf-8")
        (root / "CommonModules" / "Обычный" / "Ext").mkdir(parents=True)
        (root / "CommonModules" / "Обычный.xml").write_text(
            "<CommonModule><Name>Обычный</Name></CommonModule>",
            encoding="utf-8",
        )
        ordinary_module = root / "CommonModules" / "Обычный" / "Ext" / "Module.bsl"
        ordinary_module.write_text(
            "Процедура НетЭкспорта()\n    ЛокальныйМетод();\nКонецПроцедуры\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "onec_hbk_bsl.analysis.diagnostics._common_module_privileged_map_cached",
            lambda *_args, **_kwargs: pytest.fail(
                "privileged index is not expected for a local-only BSL231 candidate"
            ),
        )
        diags = DiagnosticEngine(select={"BSL231"}).check_file(str(ordinary_module))
        assert "BSL231" not in _codes(diags)

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

        original = diagnostics_mod._common_module_exported_proc_names_for_module_cached
        calls: set[str] = set()

        def spy(config_root: str, module_name_cf: str) -> frozenset[str]:
            calls.add(module_name_cf)
            return original(config_root, module_name_cf)

        monkeypatch.setattr(
            "onec_hbk_bsl.analysis.diagnostics._common_module_exported_proc_names_for_module_cached",
            spy,
        )
        diags = DiagnosticEngine(select={"BSL213"}).check_file(str(caller_module))
        assert "BSL213" in _codes(diags)
        assert "target" in calls
        assert "unused" not in calls

    def test_bsl213_reports_external_non_exported_common_module_method(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path / "Config"
        root.mkdir(parents=True)
        (root / "Configuration.xml").write_text("<Configuration/>", encoding="utf-8")
        for module_name in ("Caller", "Target"):
            (root / "CommonModules" / module_name / "Ext").mkdir(parents=True)
            (root / "CommonModules" / f"{module_name}.xml").write_text(
                f"<CommonModule><Name>{module_name}</Name></CommonModule>", encoding="utf-8"
            )
        caller_module = root / "CommonModules" / "Caller" / "Ext" / "Module.bsl"
        caller_module.write_text(
            textwrap.dedent(
                """\
                Процедура Run()
                    Target.PrivateMethod();
                    Target.Absent();
                    Target.Exists();
                    Caller.PrivateSelf();
                КонецПроцедуры

                Процедура PrivateSelf()
                КонецПроцедуры
                """
            ),
            encoding="utf-8",
        )
        (root / "CommonModules" / "Target" / "Ext" / "Module.bsl").write_text(
            textwrap.dedent(
                """\
                Процедура Exists() Экспорт
                КонецПроцедуры

                Процедура PrivateMethod()
                КонецПроцедуры
                """
            ),
            encoding="utf-8",
        )

        diags = [
            diag
            for diag in DiagnosticEngine(select={"BSL213"}).check_file(str(caller_module))
            if diag.code == "BSL213"
        ]

        assert [(diag.line, diag.character, diag.end_character) for diag in diags] == [
            (2, 4, 24),
            (3, 4, 17),
        ]

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

    def test_bsl253_http_timeout_argument_is_clean(self, tmp_path: Path) -> None:
        diags = _check(
            """\
            Процедура Метод()
                Соединение = Новый HTTPСоединение(Сервер,,,,, 30, Защита);
            КонецПроцедуры
            """,
            tmp_path,
            select={"BSL253"},
        )

        assert "BSL253" not in _codes(diags)

    def test_bsl253_later_timeout_assignment_is_clean(self, tmp_path: Path) -> None:
        diags = _check(
            """\
            Процедура Метод()
                Соединение = Новый HTTPСоединение(Сервер);
                Соединение.Таймаут = Таймаут;
            КонецПроцедуры
            """,
            tmp_path,
            select={"BSL253"},
        )

        assert "BSL253" not in _codes(diags)

    def test_bsl253_unsupported_constructor_comment_and_string_are_clean(
        self, tmp_path: Path
    ) -> None:
        diags = _check(
            """\
            Процедура Метод()
                Запрос = Новый HTTPЗапрос("x");
                Текст = "Новый HTTPСоединение(""x"")";
                // Новый FTPСоединение("x");
            КонецПроцедуры
            """,
            tmp_path,
            select={"BSL253"},
        )

        assert "BSL253" not in _codes(diags)

    def test_bsl261_reports_implicit_safe_mode_conditions(self, tmp_path: Path) -> None:
        diags = _check(
            """\
            Процедура Метод()
                Если БезопасныйРежим() Тогда
                КонецЕсли;
                Если Не БезопасныйРежим() Тогда
                КонецЕсли;
                Если Флаг Или SafeMode() Тогда
                КонецЕсли;
            КонецПроцедуры
            """,
            tmp_path,
            select={"BSL261"},
        )

        assert _codes(diags).count("BSL261") == 3

    def test_bsl261_explicit_comparison_assignment_setter_comment_and_string_are_clean(
        self, tmp_path: Path
    ) -> None:
        diags = _check(
            """\
            Процедура Метод()
                Если БезопасныйРежим() = Истина Тогда
                КонецЕсли;
                Если БезопасныйРежим() <> Ложь И Флаг Тогда
                КонецЕсли;
                Значение = БезопасныйРежим();
                УстановитьБезопасныйРежим(Истина);
                Текст = "Если БезопасныйРежим() Тогда";
                // Если БезопасныйРежим() Тогда
            КонецПроцедуры
            """,
            tmp_path,
            select={"BSL261"},
        )

        assert "BSL261" not in _codes(diags)


# BSL220 — TestBsl220MultilineStringInQuery
class TestBsl220MultilineStringInQuery:
    def test_upstream_shaped_multiline_string_facts(self, tmp_path: Path) -> None:
        content = '''\
            Процедура Тест()
                ТекстЗапроса =
                "ВЫБРАТь
                |   Поле КАК Поле,
                |   "" КАК ПустаяСтрока,
                |   "" КАК ЕщеПустаяСтрока,
                |   "" как ТретьяПустаяСтрока,
                |   ЕСТЬNULL(Поле, """") КАК ПолеНеВСтроке
                |ИЗ
                |   Справочник.Справочник";

                Запрос = Новый Запрос;
                Запрос.Текст = "ВЫБРАТЬ
                |   Таблица.Ссылка КАК Ссылка,
                |   ЕСТЬNULL(Таблица.Код, "") КАК Код,
                |   ЕСТЬNULL(Таблица.Наименование, "") КАК Наименование
                |ИЗ
                |   Справочник.Номенклатура КАК Таблица";
            КонецПроцедуры
        '''
        diags = [
            diag for diag in _check(content, tmp_path, select={"BSL220"}) if diag.code == "BSL220"
        ]

        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (5, 9, 6, 9),
        ]

    def test_escaped_empty_query_string_is_not_multiline_string(self, tmp_path: Path) -> None:
        content = '''\
            Процедура Тест()
                ТекстЗапроса =
                "ВЫБРАТЬ
                |   """""""" КАК Пусто,
                |   0 КАК Количество";
            КонецПроцедуры
        '''
        assert "BSL220" not in _codes(_check(content, tmp_path, select={"BSL220"}))


# BSL235 — TestBsl235QueryParseError
class TestBsl235QueryParseError:
    def test_dynamic_query_tail_reports_full_sdbl_query_range(self, tmp_path: Path) -> None:
        content = """\
            ТекстЗапроса = "ВЫБРАТЬ
            |   Т.Дата,
            |   Т.Ссылка
            |ИЗ
            |   Документ.РасходнаяНакладная КАК Т
            |ГДЕ "
            + ?(ИспользоватьОтбор, "Т.Проведен", "НЕ Т.Проведен");
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL235"}) if d.code == "BSL235"]
        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (1, 16, 6, 4),
        ]
        assert diags[0].severity is Severity.WARNING
        assert diags[0].message == _rule_msg("BSL235")

    def test_incomplete_bare_select_is_not_a_query_parse_candidate(self, tmp_path: Path) -> None:
        content = """\
            ТекстЗапроса = "ВЫБРАТЬ ";
        """
        assert "BSL235" not in _codes(_check(content, tmp_path, select={"BSL235"}))

    def test_partial_sdbl_query_candidate_with_trailing_comma_reports(self, tmp_path: Path) -> None:
        content = """\
            ТекстЗапроса = "ВЫБРАТЬ
            |   Т.Ссылка,
            |ИЗ
            |   Документ.РасходнаяНакладная КАК Т";
        """
        diags = [d for d in _check(content, tmp_path, select={"BSL235"}) if d.code == "BSL235"]
        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (1, 16, 4, 37),
        ]

    def test_dynamic_select_prefix_without_candidate_body_is_skipped(self, tmp_path: Path) -> None:
        content = """\
            ТекстЗапроса = "ВЫБРАТЬ "
                + Поля
                + " ИЗ " + Источник;
        """
        assert "BSL235" not in _codes(_check(content, tmp_path, select={"BSL235"}))

    def test_from_fragment_without_select_candidate_is_skipped(self, tmp_path: Path) -> None:
        content = """\
            ТекстЗапроса = "Документ.РасходнаяНакладная КАК Т";
        """
        assert "BSL235" not in _codes(_check(content, tmp_path, select={"BSL235"}))


# BSL206 — TestBsl206JoinWithSubQuery
class TestBsl206JoinWithSubQuery:
    @pytest.mark.platform
    @_requires_sdbl
    def test_bsl206_reports_joined_subquery_source(self, tmp_path: Path) -> None:
        content = """\
            ТекстЗапроса = "ВЫБРАТЬ
            |   Т.Ссылка
            |ИЗ
            |   Справочник.Тест КАК Т
            |   ЛЕВОЕ СОЕДИНЕНИЕ (ВЫБРАТЬ U.Ссылка КАК Ссылка ИЗ Справочник.Другой КАК U) КАК S
            |   ПО Т.Ссылка = S.Ссылка";
        """

        diags = [d for d in _check(content, tmp_path, select={"BSL206"}) if d.code == "BSL206"]

        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (5, 22, 5, 76),
        ]
        assert diags[0].severity is Severity.WARNING

    @pytest.mark.platform
    @_requires_sdbl
    def test_bsl206_reports_initial_subquery_source_with_join(self, tmp_path: Path) -> None:
        content = """\
            ТекстЗапроса = "ВЫБРАТЬ
            |   T.Ссылка
            |ИЗ
            |   (ВЫБРАТЬ U.Ссылка КАК Ссылка ИЗ Справочник.Другой КАК U) КАК T
            |   ЛЕВОЕ СОЕДИНЕНИЕ Справочник.Тест КАК S
            |   ПО T.Ссылка = S.Ссылка";
        """

        diags = [d for d in _check(content, tmp_path, select={"BSL206"}) if d.code == "BSL206"]

        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (4, 5, 4, 59),
        ]

    @pytest.mark.platform
    @_requires_sdbl
    def test_bsl206_skips_standalone_subquery_source(self, tmp_path: Path) -> None:
        content = """\
            ТекстЗапроса = "ВЫБРАТЬ
            |   T.Ссылка
            |ИЗ
            |   (ВЫБРАТЬ U.Ссылка КАК Ссылка ИЗ Справочник.Другой КАК U) КАК T";
        """

        assert "BSL206" not in _codes(_check(content, tmp_path, select={"BSL206"}))


# BSL207 — TestBsl207JoinWithVirtualTable
class TestBsl207JoinWithVirtualTable:
    @pytest.mark.platform
    @_requires_sdbl
    def test_bsl207_reports_joined_virtual_table_source(self, tmp_path: Path) -> None:
        content = """\
            ТекстЗапроса = "ВЫБРАТЬ
            |   T.Ссылка
            |ИЗ
            |   Справочник.Тест КАК S
            |   ЛЕВОЕ СОЕДИНЕНИЕ РегистрНакопления.Товары.Остатки(&Дата) КАК T
            |   ПО T.Ссылка = S.Ссылка";
        """

        diags = [d for d in _check(content, tmp_path, select={"BSL207"}) if d.code == "BSL207"]

        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (5, 21, 5, 60),
        ]
        assert diags[0].severity is Severity.WARNING

    @pytest.mark.platform
    @_requires_sdbl
    def test_bsl207_reports_initial_virtual_table_source_with_join(self, tmp_path: Path) -> None:
        content = """\
            ТекстЗапроса = "ВЫБРАТЬ
            |   T.Ссылка
            |ИЗ
            |   РегистрНакопления.Товары.Остатки(&Дата) КАК T
            |   ЛЕВОЕ СОЕДИНЕНИЕ Справочник.Тест КАК S
            |   ПО T.Ссылка = S.Ссылка";
        """

        diags = [d for d in _check(content, tmp_path, select={"BSL207"}) if d.code == "BSL207"]

        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (4, 4, 4, 43),
        ]

    @pytest.mark.platform
    @_requires_sdbl
    def test_bsl207_skips_standalone_virtual_table_source(self, tmp_path: Path) -> None:
        content = """\
            ТекстЗапроса = "ВЫБРАТЬ
            |   T.Ссылка
            |ИЗ
            |   РегистрНакопления.Товары.Остатки(&Дата) КАК T";
        """

        assert "BSL207" not in _codes(_check(content, tmp_path, select={"BSL207"}))


# BSL209 — TestBsl209LogicalOrInJoinQuerySection
class TestBsl209LogicalOrInJoinQuerySection:
    @pytest.mark.platform
    @_requires_sdbl
    def test_bsl209_reports_join_or_for_different_fields(self, tmp_path: Path) -> None:
        content = """\
            ТекстЗапроса = "ВЫБРАТЬ
            |   T.Ссылка
            |ИЗ
            |   Справочник.Тест КАК T
            |   ЛЕВОЕ СОЕДИНЕНИЕ Справочник.Другой КАК S
            |   ПО T.Ссылка = S.Ссылка
            |      И (T.Код = S.Код ИЛИ T.Наименование = S.Наименование)";
        """

        diags = [d for d in _check(content, tmp_path, select={"BSL209"}) if d.code == "BSL209"]

        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (7, 24, 7, 27),
        ]
        assert diags[0].severity is Severity.WARNING

    @pytest.mark.platform
    @_requires_sdbl
    def test_bsl209_skips_join_or_for_same_field(self, tmp_path: Path) -> None:
        content = """\
            ТекстЗапроса = "ВЫБРАТЬ
            |   T.Ссылка
            |ИЗ
            |   Справочник.Тест КАК T
            |   ЛЕВОЕ СОЕДИНЕНИЕ Справочник.Другой КАК S
            |   ПО T.Ссылка = S.Ссылка
            |      И (T.Код = 1 ИЛИ T.Код = 2)";
        """

        assert "BSL209" not in _codes(_check(content, tmp_path, select={"BSL209"}))

    @pytest.mark.platform
    @_requires_sdbl
    def test_bsl209_skips_where_or(self, tmp_path: Path) -> None:
        content = """\
            ТекстЗапроса = "ВЫБРАТЬ
            |   T.Ссылка
            |ИЗ
            |   Справочник.Тест КАК T
            |   ЛЕВОЕ СОЕДИНЕНИЕ Справочник.Другой КАК S
            |   ПО T.Ссылка = S.Ссылка
            |ГДЕ T.Код = 1 ИЛИ T.Наименование = &Имя";
        """

        assert "BSL209" not in _codes(_check(content, tmp_path, select={"BSL209"}))


# BSL201 — TestBsl201IncorrectUseLikeInQuery
class TestBsl201IncorrectUseLikeInQuery:
    @pytest.mark.platform
    @_requires_sdbl
    def test_bsl201_reports_non_parameter_non_string_rhs(self, tmp_path: Path) -> None:
        content = """\
            ТекстЗапроса = "ВЫБРАТЬ
            |   Т.Ссылка
            |ИЗ
            |   Справочник.Тест КАК Т
            |ГДЕ Т.Код ПОДОБНО ДругаяКолонка
            |   И Т.Имя ПОДОБНО Неопределено
            |   И Т.Номер ПОДОБНО 1";
        """

        diags = [d for d in _check(content, tmp_path, select={"BSL201"}) if d.code == "BSL201"]

        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (5, 5, 5, 32),
            (6, 6, 6, 32),
            (7, 6, 7, 23),
        ]
        assert {diag.severity for diag in diags} == {Severity.WARNING}

    @pytest.mark.platform
    @_requires_sdbl
    def test_bsl201_allows_parameter_and_string_rhs(self, tmp_path: Path) -> None:
        content = """\
            ТекстЗапроса = "ВЫБРАТЬ
            |   Т.Ссылка
            |ИЗ
            |   Справочник.Тест КАК Т
            |ГДЕ Т.Код ПОДОБНО &Шаблон
            |   И Т.Имя ПОДОБНО ""ABC%""
            |   И Т.Номер LIKE &Pattern";
        """

        assert "BSL201" not in _codes(_check(content, tmp_path, select={"BSL201"}))

    @pytest.mark.platform
    @_requires_sdbl
    def test_bsl201_matches_bslls_first_primitive_behavior(self, tmp_path: Path) -> None:
        content = """\
            ТекстЗапроса = "ВЫБРАТЬ
            |   Т.Ссылка
            |ИЗ
            |   Справочник.Тест КАК Т
            |ГДЕ Т.Код ПОДОБНО СтрЗаменить(&Шаблон, ""*"", ""%"")
            |   И Т.Имя ПОДОБНО &Шаблон + ""%""
            |   И Т.Номер ПОДОБНО ""%"" + &Шаблон";
        """

        assert "BSL201" not in _codes(_check(content, tmp_path, select={"BSL201"}))

    @pytest.mark.platform
    @_requires_sdbl
    def test_bsl201_skips_like_inside_query_string_literal(self, tmp_path: Path) -> None:
        content = '''\
            ТекстЗапроса = "ВЫБРАТЬ
            |   Т.Ссылка
            |ИЗ
            |   Справочник.Тест КАК Т
            |ГДЕ Т.Код = &Код
            |   И Т.Имя = ""LIKE Поле""";
        '''

        assert "BSL201" not in _codes(_check(content, tmp_path, select={"BSL201"}))


# BSL269 — TestBsl269UsingLikeInQuery
class TestBsl269UsingLikeInQuery:
    @pytest.mark.platform
    @_requires_sdbl
    def test_bsl269_reports_full_like_expression_range(self, tmp_path: Path) -> None:
        content = """\
            ТекстЗапроса = "ВЫБРАТЬ
            |   Т.Ссылка
            |ИЗ
            |   Справочник.Тест КАК Т
            |ГДЕ Т.Код ПОДОБНО &Шаблон";
        """

        diags = [d for d in _check(content, tmp_path, select={"BSL269"}) if d.code == "BSL269"]

        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (5, 5, 5, 26),
        ]
        assert diags[0].severity is Severity.INFORMATION

    @pytest.mark.platform
    @_requires_sdbl
    def test_bsl269_reports_english_like_expression(self, tmp_path: Path) -> None:
        content = """\
            QueryText = "SELECT
            |   T.Ref
            |FROM
            |   Catalog.Test AS T
            |WHERE T.Code LIKE &Pattern";
        """

        diags = [d for d in _check(content, tmp_path, select={"BSL269"}) if d.code == "BSL269"]

        assert [(d.line, d.character, d.end_line, d.end_character) for d in diags] == [
            (5, 7, 5, 27),
        ]

    @pytest.mark.platform
    @_requires_sdbl
    def test_bsl269_skips_non_like_and_like_inside_string(self, tmp_path: Path) -> None:
        content = '''\
            ТекстЗапроса = "ВЫБРАТЬ
            |   Т.Ссылка
            |ИЗ
            |   Справочник.Тест КАК Т
            |ГДЕ Т.Код = &Код
            |   И Т.Имя = ""LIKE""";
        '''

        assert "BSL269" not in _codes(_check(content, tmp_path, select={"BSL269"}))
