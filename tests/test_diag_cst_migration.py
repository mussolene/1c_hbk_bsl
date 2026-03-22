"""CST-first rules when tree-sitter parse has no ERROR nodes (see diagnostics_cst)."""

from __future__ import annotations

from pathlib import Path

import pytest

from onec_hbk_bsl.analysis.diagnostics import DiagnosticEngine
from onec_hbk_bsl.parser.bsl_parser import BslParser


@pytest.mark.parametrize(
    "code,rule,expect_line",
    [
        (
            "Процедура Т()\n"
            "    Если НЕ НЕ Истина Тогда\n"
            "    КонецЕсли;\n"
            "КонецПроцедуры\n",
            "BSL060",
            2,
        ),
        (
            "Процедура Т()\n"
            "    ВызватьИсключение \"msg\";\n"
            "КонецПроцедуры\n",
            "BSL018",
            2,
        ),
        (
            "Процедура Т()\n"
            "    Если Истина Тогда\n"
            "    КонецЕсли;\n"
            "КонецПроцедуры\n",
            "BSL085",
            2,
        ),
        (
            "Процедура Т()\n"
            "Попытка\n"
            "    А = 1;\n"
            "Исключение\n"
            "КонецПопытки\n"
            "КонецПроцедуры\n",
            "BSL004",
            4,
        ),
        (
            "Процедура Т()\n"
            "Пока Истина Цикл\n"
            "    // x\n"
            "КонецЦикла\n"
            "КонецПроцедуры\n",
            "BSL070",
            2,
        ),
        (
            "Процедура Т()\n"
            "Пока Истина Цикл\n"
            "    Прервать;\n"
            "КонецЦикла\n"
            "КонецПроцедуры\n",
            "BSL061",
            3,
        ),
    ],
)
def test_cst_rule_emits_on_fixture(
    tmp_path: Path, code: str, rule: str, expect_line: int
) -> None:
    p = tmp_path / "m.bsl"
    p.write_text(code, encoding="utf-8")
    engine = DiagnosticEngine(parser=BslParser(), select={rule})
    diags = engine.check_file(str(p))
    hit = [d for d in diags if d.code == rule]
    assert hit, f"expected {rule}"
    assert hit[0].line == expect_line


def test_bsl018_cst_extended_raise_not_flagged(tmp_path: Path) -> None:
    p = tmp_path / "m.bsl"
    p.write_text(
        'ВызватьИсключение("msg", КатегорияОшибки.Прочие);\n',
        encoding="utf-8",
    )
    engine = DiagnosticEngine(parser=BslParser(), select={"BSL018"})
    diags = engine.check_file(str(p))
    assert not any(d.code == "BSL018" for d in diags)


def test_bsl091_cst_elseif_return_then_else(tmp_path: Path) -> None:
    p = tmp_path / "m.bsl"
    p.write_text(
        "Процедура Т()\n"
        "Если Ложь Тогда\n"
        "    А = 1;\n"
        "ИначеЕсли Истина Тогда\n"
        "    Возврат;\n"
        "Иначе\n"
        "    Б = 2;\n"
        "КонецЕсли;\n"
        "КонецПроцедуры\n",
        encoding="utf-8",
    )
    engine = DiagnosticEngine(parser=BslParser(), select={"BSL091"})
    diags = engine.check_file(str(p))
    lines = {d.line for d in diags if d.code == "BSL091"}
    assert lines == {6}


def test_bsl092_cst_empty_else(tmp_path: Path) -> None:
    p = tmp_path / "m.bsl"
    p.write_text(
        "Процедура Т()\n"
        "Если Истина Тогда\n"
        "    Возврат;\n"
        "Иначе\n"
        "КонецЕсли;\n"
        "КонецПроцедуры\n",
        encoding="utf-8",
    )
    engine = DiagnosticEngine(parser=BslParser(), select={"BSL092"})
    diags = engine.check_file(str(p))
    assert any(d.code == "BSL092" and d.line == 4 for d in diags)


def test_bsl033_cst_query_in_loop(tmp_path: Path) -> None:
    p = tmp_path / "m.bsl"
    p.write_text(
        "Процедура Т()\n"
        "З = Новый Запрос;\n"
        "Пока Истина Цикл\n"
        "    З.Выполнить();\n"
        "КонецЦикла\n"
        "КонецПроцедуры\n",
        encoding="utf-8",
    )
    engine = DiagnosticEngine(parser=BslParser(), select={"BSL033"})
    diags = engine.check_file(str(p))
    assert any(d.code == "BSL033" and d.line == 4 for d in diags)
