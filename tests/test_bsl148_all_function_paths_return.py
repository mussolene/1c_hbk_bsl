"""BSL148 AllFunctionPathMustHaveReturn — BSLLS fixture parity (default loop option)."""

from __future__ import annotations

from pathlib import Path

import pytest

from onec_hbk_bsl.analysis.diagnostics import DiagnosticEngine

_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "diag_bslls"
    / "AllFunctionPathMustHaveReturnDiagnostic.bsl"
)


@pytest.mark.skipif(not _FIXTURE.is_file(), reason="copy from BSLLS diagnostics resources")
def test_bsl148_matches_bslls_default_fixture() -> None:
    engine = DiagnosticEngine(select={"BSL148"})
    diags = [d for d in engine.check_file(str(_FIXTURE)) if d.code == "BSL148"]
    lines = sorted({d.line for d in diags})
    assert lines == [1, 26, 94, 103, 132]


@pytest.mark.skipif(not _FIXTURE.is_file(), reason="copy from BSLLS diagnostics resources")
def test_bsl148_loops_false_adds_for_loop_case() -> None:
    engine = DiagnosticEngine(
        select={"BSL148"},
        bsl148_loops_executed_at_least_once=False,
    )
    diags = [d for d in engine.check_file(str(_FIXTURE)) if d.code == "BSL148"]
    lines = sorted({d.line for d in diags})
    assert lines == [1, 26, 37, 94, 103, 132]


def test_bsl148_ignores_return_in_nested_routine(tmp_path: Path) -> None:
    content = (
        "Функция Внешняя()\n"
        "    Функция Внутренняя()\n"
        "        Возврат Истина;\n"
        "    КонецФункции\n"
        "КонецФункции\n"
    )
    path = tmp_path / "nested_return.bsl"
    path.write_text(content, encoding="utf-8")
    engine = DiagnosticEngine(select={"BSL148"})
    diags = [d for d in engine.check_file(str(path)) if d.code == "BSL148"]
    assert diags == []


def test_bsl148_nested_if_with_total_returns_is_not_reported(tmp_path: Path) -> None:
    content = (
        "Функция Внешняя(Флаг)\n"
        "    Если Флаг Тогда\n"
        "        Если Истина Тогда\n"
        "            Возврат 1;\n"
        "        Иначе\n"
        "            Возврат 2;\n"
        "        КонецЕсли;\n"
        "    Иначе\n"
        "        Возврат 3;\n"
        "    КонецЕсли;\n"
        "КонецФункции\n"
    )
    path = tmp_path / "nested_if_total_returns.bsl"
    path.write_text(content, encoding="utf-8")
    diags = [
        d for d in DiagnosticEngine(select={"BSL148"}).check_file(str(path)) if d.code == "BSL148"
    ]
    assert diags == []


def test_bsl148_anchor_points_to_function_identifier(tmp_path: Path) -> None:
    content = (
        "Функция Тест(Флаг)\n"
        "    Если Флаг Тогда\n"
        "        Возврат 1;\n"
        "    КонецЕсли;\n"
        "КонецФункции\n"
    )
    path = tmp_path / "anchor_identifier.bsl"
    path.write_text(content, encoding="utf-8")
    diags = [
        d for d in DiagnosticEngine(select={"BSL148"}).check_file(str(path)) if d.code == "BSL148"
    ]
    assert len(diags) == 1
    assert diags[0].line == 1
    assert diags[0].character == 8
    assert diags[0].end_character > diags[0].character


def test_bsl148_try_except_with_guaranteed_returns_is_not_reported(tmp_path: Path) -> None:
    content = (
        "Функция Тест(Флаг)\n"
        "    Попытка\n"
        "        Если Флаг Тогда\n"
        "            Возврат 1;\n"
        "        Иначе\n"
        "            Возврат 2;\n"
        "        КонецЕсли;\n"
        "    Исключение\n"
        "        Возврат 0;\n"
        "    КонецПопытки;\n"
        "КонецФункции\n"
    )
    path = tmp_path / "try_except_returns.bsl"
    path.write_text(content, encoding="utf-8")
    diags = [
        d for d in DiagnosticEngine(select={"BSL148"}).check_file(str(path)) if d.code == "BSL148"
    ]
    assert diags == []
