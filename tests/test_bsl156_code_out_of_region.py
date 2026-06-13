"""BSL156 CodeOutOfRegion — procedures and module-level code inside #Область."""

from __future__ import annotations

from pathlib import Path

from onec_hbk_bsl.analysis.diagnostic.rules.module_structure_rules import (
    path_has_known_bsl156_module_type,
)
from onec_hbk_bsl.analysis.diagnostics import DiagnosticEngine


def _common_module_path(root: Path) -> Path:
    return root / "CommonModules" / "ПервыйОбщийМодуль" / "Ext" / "Module.bsl"


def test_bsl156_no_regions_flags_line1(tmp_path: Path) -> None:
    p = _common_module_path(tmp_path)
    p.parent.mkdir(parents=True)
    p.write_text(
        "Процедура П() Экспорт\nКонецПроцедуры\n",
        encoding="utf-8",
    )
    engine = DiagnosticEngine(select={"BSL156"})
    diags = [d for d in engine.check_file(str(p)) if d.code == "BSL156"]
    assert len(diags) >= 1
    assert any(d.line == 1 for d in diags)
    assert any(d.message == "Переместите код в область" for d in diags)


def test_bsl156_proc_inside_region_clean(tmp_path: Path) -> None:
    p = _common_module_path(tmp_path)
    p.parent.mkdir(parents=True)
    p.write_text(
        "#Область ПрограммныйИнтерфейс\nПроцедура П() Экспорт\nКонецПроцедуры\n#КонецОбласти\n",
        encoding="utf-8",
    )
    engine = DiagnosticEngine(select={"BSL156"})
    assert not [d for d in engine.check_file(str(p)) if d.code == "BSL156"]


def test_bsl156_split_method_file_next_to_module_is_skipped(tmp_path: Path) -> None:
    ext = tmp_path / "CommonModules" / "Модуль" / "Ext"
    ext.mkdir(parents=True)
    (ext / "Module.bsl").write_text(
        "#Область ПрограммныйИнтерфейс\nПроцедура П() Экспорт\nКонецПроцедуры\n#КонецОбласти\n",
        encoding="utf-8",
    )
    split = ext / "П.bsl"
    split.write_text(
        "Процедура П() Экспорт\nКонецПроцедуры\n",
        encoding="utf-8",
    )

    engine = DiagnosticEngine(select={"BSL156"})

    assert not [d for d in engine.check_file(str(split)) if d.code == "BSL156"]


def test_bsl156_proc_outside_region(tmp_path: Path) -> None:
    p = _common_module_path(tmp_path)
    p.parent.mkdir(parents=True)
    p.write_text(
        "Процедура Снаружи() Экспорт\n"
        "КонецПроцедуры\n"
        "#Область Внутри\n"
        "Процедура Внутри() Экспорт\n"
        "КонецПроцедуры\n"
        "#КонецОбласти\n",
        encoding="utf-8",
    )
    engine = DiagnosticEngine(select={"BSL156"})
    diags = [d for d in engine.check_file(str(p)) if d.code == "BSL156"]
    assert any(d.line == 1 for d in diags)


def test_bsl156_module_var_outside_region(tmp_path: Path) -> None:
    p = _common_module_path(tmp_path)
    p.parent.mkdir(parents=True)
    p.write_text(
        "#Область О\nПроцедура П() Экспорт\nКонецПроцедуры\n#КонецОбласти\nПерем Глоб;\n",
        encoding="utf-8",
    )
    engine = DiagnosticEngine(select={"BSL156"})
    diags = [d for d in engine.check_file(str(p)) if d.code == "BSL156"]
    lines = {d.line for d in diags}
    assert 5 in lines


def test_bsl156_form_module_without_regions_reports_procedure(tmp_path: Path) -> None:
    p = tmp_path / "Forms" / "ФормаСписка" / "Ext" / "Form" / "Module.bsl"
    p.parent.mkdir(parents=True)
    p.write_text(
        "&НаСервере\nПроцедура ПриСозданииНаСервере(Отказ, СтандартнаяОбработка)\nКонецПроцедуры\n",
        encoding="utf-8",
    )
    engine = DiagnosticEngine(select={"BSL156"})
    diags = [d for d in engine.check_file(str(p)) if d.code == "BSL156"]
    assert len(diags) == 1
    assert diags[0].line == 2
    assert diags[0].character == 10


def test_bsl156_no_regions_inside_preprocessor_is_skipped(tmp_path: Path) -> None:
    p = tmp_path / "InformationRegisters" / "РегистрСведений1" / "Ext" / "RecordSetModule.bsl"
    p.parent.mkdir(parents=True)
    p.write_text(
        "#Если Сервер Тогда\n"
        "Процедура ПередЗаписью(Отказ, Замещение)\n"
        "КонецПроцедуры\n"
        "#КонецЕсли\n",
        encoding="utf-8",
    )
    engine = DiagnosticEngine(select={"BSL156"})
    diags = [d for d in engine.check_file(str(p)) if d.code == "BSL156"]
    assert len(diags) == 1
    assert diags[0].line == 2
    assert diags[0].character == 10


def test_bsl156_unknown_module_type_is_skipped_by_default(tmp_path: Path) -> None:
    p = tmp_path / "AnySnippet.bsl"
    p.write_text(
        "Процедура П() Экспорт\nКонецПроцедуры\n",
        encoding="utf-8",
    )
    engine = DiagnosticEngine(select={"BSL156"})
    assert not [d for d in engine.check_file(str(p)) if d.code == "BSL156"]


def test_bsl156_known_module_type_paths_match_bslls_fixtures() -> None:
    known_paths = [
        "Catalogs/Справочник1/Commands/Команда1/Ext/CommandModule.bsl",
        "Catalogs/Справочник1/Ext/ObjectModule.bsl",
        "Catalogs/Справочник1/Ext/ManagerModule.bsl",
        "Ext/ManagedApplicationModule.bsl",
        "Ext/SessionModule.bsl",
        "Ext/ExternalConnectionModule.bsl",
        "Catalogs/Справочник1/Forms/ФормаЭлемента/Ext/Form/Module.bsl",
        "Catalogs/Справочник1/Forms/ФормаЭлемента/Ext/Module.bsl",
        "CommonModules/ПервыйОбщийМодуль/Ext/Module.bsl",
        "InformationRegisters/РегистрСведений1/Ext/RecordSetModule.bsl",
        "HTTPServices/HTTPСервис1/Ext/Module.bsl",
        "WebServices/WebСервис1/Ext/Module.bsl",
    ]
    for path in known_paths:
        assert path_has_known_bsl156_module_type(path), path

    unknown_paths = [
        "Module.bsl",
        "AnySnippet.bsl",
        "Catalogs/Справочник1/SomeMethod.bsl",
        "CommonModules/ПервыйОбщийМодуль/Ext/SomeMethod.bsl",
    ]
    for path in unknown_paths:
        assert not path_has_known_bsl156_module_type(path), path
