"""CST-first BSL009/BSL059 when tree-sitter parse has no ERROR nodes."""
from __future__ import annotations

from pathlib import Path

from onec_hbk_bsl.analysis.diagnostics import DiagnosticEngine
from onec_hbk_bsl.parser.bsl_parser import BslParser


def test_bsl009_cst_ignores_property_copy(tmp_path: Path) -> None:
    p = tmp_path / "m.bsl"
    p.write_text(
        "Процедура Т()\n"
        "    Описание.Поле = Поле;\n"
        "КонецПроцедуры\n",
        encoding="utf-8",
    )
    engine = DiagnosticEngine(parser=BslParser(), select={"BSL009"})
    diags = engine.check_file(str(p))
    assert not any(d.code == "BSL009" for d in diags)


def test_bsl059_cst_only_if_condition(tmp_path: Path) -> None:
    p = tmp_path / "m.bsl"
    p.write_text(
        "Процедура Т()\n"
        "    Флаг = Ложь;\n"
        "    Если А = Истина Тогда\n"
        "        Х = 1;\n"
        "    КонецЕсли;\n"
        "КонецПроцедуры\n",
        encoding="utf-8",
    )
    engine = DiagnosticEngine(parser=BslParser(), select={"BSL059"})
    diags = engine.check_file(str(p))
    lines = {d.line for d in diags if d.code == "BSL059"}
    assert lines == {3}


def test_bsl059_cst_elseif(tmp_path: Path) -> None:
    p = tmp_path / "m.bsl"
    p.write_text(
        "Если А Тогда\n"
        "    Х = 1;\n"
        "ИначеЕсли Б = Ложь Тогда\n"
        "    У = 2;\n"
        "КонецЕсли;\n",
        encoding="utf-8",
    )
    engine = DiagnosticEngine(parser=BslParser(), select={"BSL059"})
    diags = engine.check_file(str(p))
    assert any(d.code == "BSL059" for d in diags)
