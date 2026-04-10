"""BSL156 CodeOutOfRegion — procedures and module-level code inside #Область."""

from __future__ import annotations

from pathlib import Path

from onec_hbk_bsl.analysis.diagnostics import DiagnosticEngine


def test_bsl156_no_regions_flags_line1(tmp_path: Path) -> None:
    p = tmp_path / "m.bsl"
    p.write_text(
        "Процедура П() Экспорт\nКонецПроцедуры\n",
        encoding="utf-8",
    )
    engine = DiagnosticEngine(select={"BSL156"})
    diags = [d for d in engine.check_file(str(p)) if d.code == "BSL156"]
    assert len(diags) >= 1
    assert any(d.line == 1 for d in diags)


def test_bsl156_proc_inside_region_clean(tmp_path: Path) -> None:
    p = tmp_path / "m.bsl"
    p.write_text(
        "#Область ПрограммныйИнтерфейс\nПроцедура П() Экспорт\nКонецПроцедуры\n#КонецОбласти\n",
        encoding="utf-8",
    )
    engine = DiagnosticEngine(select={"BSL156"})
    assert not [d for d in engine.check_file(str(p)) if d.code == "BSL156"]


def test_bsl156_proc_outside_region(tmp_path: Path) -> None:
    p = tmp_path / "m.bsl"
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
    p = tmp_path / "m.bsl"
    p.write_text(
        "#Область О\nПроцедура П() Экспорт\nКонецПроцедуры\n#КонецОбласти\nПерем Глоб;\n",
        encoding="utf-8",
    )
    engine = DiagnosticEngine(select={"BSL156"})
    diags = [d for d in engine.check_file(str(p)) if d.code == "BSL156"]
    lines = {d.line for d in diags}
    assert 5 in lines


def test_bsl156_form_module_without_regions_is_skipped(tmp_path: Path) -> None:
    p = tmp_path / "Forms" / "ФормаСписка" / "Ext" / "Form" / "Module.bsl"
    p.parent.mkdir(parents=True)
    p.write_text(
        "&НаСервере\nПроцедура ПриСозданииНаСервере(Отказ, СтандартнаяОбработка)\nКонецПроцедуры\n",
        encoding="utf-8",
    )
    engine = DiagnosticEngine(select={"BSL156"})
    assert not [d for d in engine.check_file(str(p)) if d.code == "BSL156"]


def test_bsl156_no_regions_inside_preprocessor_is_skipped(tmp_path: Path) -> None:
    p = tmp_path / "RecordSetModule.bsl"
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
