"""BSL154 CodeAfterAsyncCall — BSLLS-style async call + following code (opt-in rule)."""

from __future__ import annotations

from pathlib import Path

from onec_hbk_bsl.analysis.diagnostic.rules.module_structure_rules import (
    path_matches_bsl154_module_types,
)
from onec_hbk_bsl.analysis.diagnostics import DiagnosticEngine


def _form_module_path(root: Path) -> Path:
    return root / "Catalogs" / "Тест" / "Forms" / "Форма" / "Ext" / "Form" / "Module.bsl"


def test_bsl154_path_guards() -> None:
    assert path_matches_bsl154_module_types(r"C:\cfg\Catalogs\X\Forms\F\Ext\Form\Module.bsl")
    assert path_matches_bsl154_module_types("/app/CommonCommands/Foo/Ext/CommandModule.bsl")
    assert path_matches_bsl154_module_types(
        "/base/Ext/ManagedApplicationModule/ManagedApplicationModule.bsl"
    )
    assert not path_matches_bsl154_module_types("/CommonModules/M/Ext/Module.bsl")


def test_bsl154_fires_when_code_follows_async(tmp_path: Path) -> None:
    p = _form_module_path(tmp_path)
    p.parent.mkdir(parents=True)
    p.write_text(
        'Процедура ПриОткрытии()\n    ПоказатьВопрос("?");\n    x = 1;\nКонецПроцедуры\n',
        encoding="utf-8",
    )
    engine = DiagnosticEngine(select={"BSL154"})
    diags = [d for d in engine.check_file(str(p)) if d.code == "BSL154"]
    assert len(diags) == 1
    assert diags[0].line == 2
    assert "ПоказатьВопрос" in p.read_text(encoding="utf-8")


def test_bsl154_fires_when_parent_block_has_following_code(tmp_path: Path) -> None:
    p = _form_module_path(tmp_path)
    p.parent.mkdir(parents=True)
    p.write_text(
        "Процедура ПриОткрытии()\n"
        "    Если Истина Тогда\n"
        '        ПоказатьВопрос("?");\n'
        "    КонецЕсли;\n"
        "    x = 1;\n"
        "КонецПроцедуры\n",
        encoding="utf-8",
    )
    engine = DiagnosticEngine(select={"BSL154"})
    diags = [d for d in engine.check_file(str(p)) if d.code == "BSL154"]
    assert len(diags) == 1
    assert diags[0].line == 3


def test_bsl154_skips_when_return_follows(tmp_path: Path) -> None:
    p = _form_module_path(tmp_path)
    p.parent.mkdir(parents=True)
    p.write_text(
        'Процедура П()\n    ПоказатьВопрос("?");\n    Возврат;\nКонецПроцедуры\n',
        encoding="utf-8",
    )
    engine = DiagnosticEngine(select={"BSL154"})
    assert not [d for d in engine.check_file(str(p)) if d.code == "BSL154"]


def test_bsl154_skips_object_method_call(tmp_path: Path) -> None:
    p = _form_module_path(tmp_path)
    p.parent.mkdir(parents=True)
    p.write_text(
        'Процедура П()\n    Диалог.ПоказатьВопрос("?");\n    x = 1;\nКонецПроцедуры\n',
        encoding="utf-8",
    )
    engine = DiagnosticEngine(select={"BSL154"})
    assert not [d for d in engine.check_file(str(p)) if d.code == "BSL154"]


def test_bsl154_skips_when_break_follows(tmp_path: Path) -> None:
    p = tmp_path / "Ext" / "CommandModule.bsl"
    p.parent.mkdir(parents=True)
    p.write_text(
        "Процедура П()\n"
        "    Пока Истина Цикл\n"
        '        ShowQueryBox("?");\n'
        "        Break;\n"
        "    КонецЦикла;\n"
        "КонецПроцедуры\n",
        encoding="utf-8",
    )
    engine = DiagnosticEngine(select={"BSL154"})
    assert not [d for d in engine.check_file(str(p)) if d.code == "BSL154"]


def test_bsl154_skips_common_module_even_if_pattern_matches(tmp_path: Path) -> None:
    p = tmp_path / "CommonModules" / "M" / "Ext" / "Module.bsl"
    p.parent.mkdir(parents=True)
    p.write_text(
        'Процедура П() Экспорт\n    ПоказатьВопрос("?");\n    x = 1;\nКонецПроцедуры\n',
        encoding="utf-8",
    )
    engine = DiagnosticEngine(select={"BSL154"})
    assert not [d for d in engine.check_file(str(p)) if d.code == "BSL154"]
