"""
Parity: full-document ``BslFormatter.format`` vs style diagnostics (BSL024, BSL055, …).

Guards alignment between formatter output and rules we claim match BSLLS / fix-on-format.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from onec_hbk_bsl.analysis.diagnostics import DiagnosticEngine
from onec_hbk_bsl.analysis.formatter import BslFormatter


def _diags_after_format(content: str, tmp_path: Path, *, select: set[str]) -> list[str]:
    path = tmp_path / "parity.bsl"
    path.write_text(BslFormatter().format(content), encoding="utf-8")
    return [d.code for d in DiagnosticEngine(select=select).check_file(str(path))]


@pytest.mark.parametrize(
    ("raw", "select"),
    [
        ("//foo\nПроцедура П() Экспорт\nКонецПроцедуры\n", {"BSL024"}),
        ("А = 1;\n\n\n\n\nБ = 2;\n", {"BSL055"}),
        ("Процедура Т()\n\tА = 1;// комментарий\nКонецПроцедуры\n", {"BSL136"}),
        ("Процедура Т()\n\tА=1;\nКонецПроцедуры\n", {"BSL216"}),
    ],
)
def test_format_clears_listed_rules(
    tmp_path: Path, raw: str, select: set[str]
) -> None:
    codes = _diags_after_format(raw, tmp_path, select=select)
    unexpected = set(codes) & select
    assert not unexpected, f"after format still got {unexpected} for select={select}"


def test_unformatted_sample_triggers_bsl055(tmp_path: Path) -> None:
    raw = "А = 1;\n\n\n\nБ = 2;\n"
    path = tmp_path / "raw.bsl"
    path.write_text(raw, encoding="utf-8")
    codes = [d.code for d in DiagnosticEngine(select={"BSL055"}).check_file(str(path))]
    assert "BSL055" in codes
