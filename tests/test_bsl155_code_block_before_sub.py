"""BSL155 CodeBlockBeforeSub — lines before first procedure (excluding Перем-only)."""

from __future__ import annotations

from pathlib import Path

import pytest

from onec_hbk_bsl.analysis.diagnostics import DiagnosticEngine


def test_bsl155_skips_only_var_before_proc(tmp_path: Path) -> None:
    p = tmp_path / "m.bsl"
    p.write_text(
        "Перем Глоб;\nПроцедура П() Экспорт\nКонецПроцедуры\n",
        encoding="utf-8",
    )
    engine = DiagnosticEngine(select={"BSL155"})
    assert not [d for d in engine.check_file(str(p)) if d.code == "BSL155"]


def test_bsl155_skips_annotation_before_first_proc(tmp_path: Path) -> None:
    p = tmp_path / "m.bsl"
    p.write_text(
        "#Область Обработчики\n\n&НаСервере\nПроцедура П() Экспорт\nКонецПроцедуры\n",
        encoding="utf-8",
    )
    engine = DiagnosticEngine(select={"BSL155"})
    assert not [d for d in engine.check_file(str(p)) if d.code == "BSL155"]


def test_bsl155_fires_executable_before_proc(tmp_path: Path) -> None:
    p = tmp_path / "m.bsl"
    p.write_text(
        "а = 1;\nПроцедура П() Экспорт\nКонецПроцедуры\n",
        encoding="utf-8",
    )
    engine = DiagnosticEngine(select={"BSL155"})
    diags = [d for d in engine.check_file(str(p)) if d.code == "BSL155"]
    assert len(diags) == 1
    assert diags[0].line == 1
    assert diags[0].severity.name == "ERROR"


def test_bsl155_matches_upstream_fixture_range() -> None:
    p = Path(
        ".agent/tmp/bslls-source/src/test/resources/diagnostics/CodeBlockBeforeSubDiagnostic.bsl"
    )
    if not p.exists():
        pytest.skip("BSLLS fixture is not available")
    engine = DiagnosticEngine(select={"BSL155"})
    diags = [d for d in engine.check_file(str(p)) if d.code == "BSL155"]
    assert len(diags) == 1
    assert diags[0].line == 4
    assert diags[0].character == 0
    assert diags[0].end_line == 6
    assert diags[0].end_character == 13
